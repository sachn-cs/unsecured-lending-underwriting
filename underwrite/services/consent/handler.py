"""Consent management - DPDPA 2023 compliant consent lifecycle.

Records, tracks, and audits user consent for specific processing
purposes. Supports consent withdrawal, expiry, and re-consent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.__logger__ import logger
from underwrite.__metrics__ import SystemClock
from underwrite.services.base import StatefulService
from underwrite.services.persistence import TypedStoreRepository

from underwrite.__authz__ import AccessControl
from underwrite.__bus__ import EventBus
from underwrite.__health__ import HealthRegistry
from underwrite.__identity__ import Identity
from underwrite.__metrics__ import MetricsCollector
from underwrite.__saga__ import SagaOrchestrator
from underwrite.__store__ import Store
from underwrite.__supervisor__ import ServiceSupervisor
from underwrite.__tracer__ import Tracer

DEFAULT_CONSENT_VALIDITY_DAYS: int = 365


@dataclass(frozen=True, slots=True)
class ConsentConfig:
    """Typed configuration for ConsentHandler.

    Replaces the previous ``kwargs.pop("required_purposes", ...)``
    pattern: callers now pass a ConsentConfig (or its fields are
    extracted from kwargs via a constructor that does not mutate
    the caller's mapping).
    """

    required_purposes: list[str] = field(default_factory=list)
    consent_validity_days: int = DEFAULT_CONSENT_VALIDITY_DAYS


class ConsentHandler(StatefulService):
    """Manages the full consent lifecycle per DPDPA 2023.

    Each consent record captures:
      - user_id: the data subject
      - purpose: why the data is processed
      - status: active / withdrawn / expired
      - recorded_at / withdrawn_at / expires_at timestamps
    """

    def __init__(
        self,
        service_id: str,
        bus: EventBus,
        store: Store,
        identity: Identity | None = None,
        metrics: MetricsCollector | None = None,
        health: HealthRegistry | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: SagaOrchestrator | None = None,
        supervisor: ServiceSupervisor | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize the consent service with required purposes and validity.

        Args:
            **kwargs: May include ``required_purposes`` (list of str)
                and ``consent_validity_days`` (int). Falls back to
                empty list and 365 days respectively.

        """
        config = ConsentConfig(
            required_purposes=kwargs.pop("required_purposes", []),
            consent_validity_days=kwargs.pop("consent_validity_days", DEFAULT_CONSENT_VALIDITY_DAYS),
        )
        self.__required_purposes: list[str] = config.required_purposes
        self.__consent_validity_days: int = config.consent_validity_days
        super().__init__(
            service_id=service_id,
            identity=identity,
            bus=bus,
            store=store,
            metrics=metrics,
            health=health,
            authz=authz,
            tracer=tracer,
            saga=saga,
            supervisor=supervisor,
            secrets_manager=secrets_manager,
            max_concurrent=max_concurrent,
        )
        self.__clock: SystemClock = SystemClock()
        self.__records: dict[str, dict[str, Any]] = {}
        self.repo: TypedStoreRepository[dict[str, dict[str, Any]]] = self.store_repo("consent", dict)

    def start(self) -> None:
        """Load persisted consent records when the service starts."""
        super().start()
        loaded = self.repo.load(default={})
        if loaded:
            self.__records = loaded

    def handle(self, event: Event) -> None:
        """Process consent recording and withdrawal events.

        Args:
            event: The incoming domain event.

        """
        if event.event_type == EventType.CONSENT_RECORDED:
            self.record_consent(event)
        elif event.event_type == EventType.CONSENT_WITHDRAWN:
            self.withdraw_consent(event)

    def record_consent(self, event: Event) -> None:
        """Record a new consent for a user/purpose pair.

        Args:
            event: The CONSENT_RECORDED event with user_id, purpose,
                and optional ip_address and user_agent.

        """
        user_id: str = event.payload.get("user_id", "")
        purpose: str = event.payload.get("purpose", "")
        if not user_id or not purpose:
            logger.warning("consent.recorded missing user_id or purpose")
            return
        key = f"{user_id}:{purpose}"
        now = self.__clock.utc_now()
        expires = now + timedelta(days=self.__consent_validity_days)
        with self.state_lock:
            self.__records[key] = {
                "user_id": user_id,
                "purpose": purpose,
                "status": "active",
                "recorded_at": now.isoformat(),
                "expires_at": expires.isoformat(),
                "ip_address": event.payload.get("ip_address", ""),
                "user_agent": event.payload.get("user_agent", ""),
            }
            self.repo.save(self.__records)

    def withdraw_consent(self, event: Event) -> None:
        """Withdraw consent for a user, optionally for a specific purpose.

        Args:
            event: The CONSENT_WITHDRAWN event with user_id and
                optional purpose.

        """
        user_id: str = event.payload.get("user_id", "")
        purpose: str = event.payload.get("purpose", "")
        if not user_id:
            logger.warning("consent.withdrawn missing user_id")
            return
        with self.state_lock:
            if purpose:
                key = f"{user_id}:{purpose}"
                record = self.__records.get(key)
                if record and record.get("status") == "active":
                    record["status"] = "withdrawn"
                    record["withdrawn_at"] = self.__clock.iso()
            else:
                for key, record in self.__records.items():
                    if key.startswith(f"{user_id}:") and record.get("status") == "active":
                        record["status"] = "withdrawn"
                        record["withdrawn_at"] = self.__clock.iso()
            self.repo.save(self.__records)

    def get_consent(self, user_id: str, purpose: str) -> dict[str, Any] | None:
        """Return the consent record for a user/purpose pair.

        Args:
            user_id: The data subject identifier.
            purpose: The processing purpose.

        Returns:
            Consent record or None.

        """
        with self.state_lock:
            return self.__records.get(f"{user_id}:{purpose}")

    def has_active_consent(self, user_id: str, purpose: str) -> bool:
        """Check if a user has active, non-expired consent for a purpose.

        Args:
            user_id: The data subject identifier.
            purpose: The processing purpose.

        Returns:
            True if active and not expired.

        """
        with self.state_lock:
            record = self.__records.get(f"{user_id}:{purpose}")
            if not record:
                return False
            if record.get("status") != "active":
                return False
            expires_str = record.get("expires_at", "")
            if expires_str:
                try:
                    expires = datetime.fromisoformat(expires_str)
                    if expires < self.__clock.utc_now():
                        return False
                except (ValueError, TypeError):
                    logger.warning(
                        "invalid expires_at format for user {} purpose {}: {}",
                        user_id,
                        purpose,
                        expires_str,
                    )
            return True

    def get_user_consents(self, user_id: str) -> list[dict[str, Any]]:
        """Return all consent records for a user.

        Args:
            user_id: The data subject identifier.

        Returns:
            List of consent record dicts.

        """
        with self.state_lock:
            if not self.__records:
                return []
            return [v for k, v in self.__records.items() if k.startswith(f"{user_id}:")]

    def check_missing_purposes(self, user_id: str) -> list[str]:
        """Return required purposes for which the user lacks active consent.

        Args:
            user_id: The data subject identifier.

        Returns:
            List of purpose strings that are missing.

        """
        active = set(
            r["purpose"] for r in self.get_user_consents(user_id) if self.has_active_consent(user_id, r["purpose"])
        )
        return [p for p in self.__required_purposes if p not in active]
