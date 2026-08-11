# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Data Subject Rights (DSR) - DPDPA 2023 compliant request handling.

Manages data subject requests for access, correction, erasure, and
grievance redressal as required by the Digital Personal Data
Protection Act 2023.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.local import LocalBus
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.metrics import Collector
from underwrite.saga import Orchestrator
from underwrite.services.base import Dependencies, StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.store import StoreBackend
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.value_objects import IdGenerator

DEFAULT_DSR_RESPONSE_DAYS: int = 30
DEFAULT_GRIEVANCE_RESPONSE_DAYS: int = 15


@dataclass(frozen=True, slots=True)
class DsrConfig:
    """Typed configuration for Handler.

    Replaces the previous ``kwargs.pop("response_time_days", ...)``
    pattern: callers now pass a DsrConfig (or its fields are
    extracted from kwargs via a constructor that does not mutate
    the caller's mapping).
    """

    response_time_days: int = DEFAULT_DSR_RESPONSE_DAYS
    grievance_response_days: int = DEFAULT_GRIEVANCE_RESPONSE_DAYS


class Handler(StatefulService):
    """Handles DSR requests and grievance redressal per DPDPA 2023.

    Supports:
      - Data access requests (user wants their data)
      - Data correction requests (user wants to fix inaccurate data)
      - Data erasure requests (right to be forgotten)
      - Grievance logging and resolution
    """

    def __init__(
        self,
        name: str,
        bus: EventBus | LocalBus,
        store: StoreBackend,
        identity: Keypair | None = None,
        metrics: Collector | None = None,
        health: Checks | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: Orchestrator | None = None,
        supervisor: Watcher | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
        **kwargs: Any,
    ) -> None:
        config = DsrConfig(
            response_time_days=kwargs.pop("response_time_days", DEFAULT_DSR_RESPONSE_DAYS),
            grievance_response_days=kwargs.pop("grievance_response_days", DEFAULT_GRIEVANCE_RESPONSE_DAYS),
        )
        self.response_days: int = config.response_time_days
        self.grievance_days: int = config.grievance_response_days
        deps = Dependencies(
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
        super().__init__(
            name=name,
            bus=deps.bus,
            store=deps.store,
            metrics=deps.metrics,
            health=deps.health,
            authz=deps.authz,
            tracer=deps.tracer,
            saga=deps.saga,
            supervisor=deps.supervisor,
            secrets_manager=deps.secrets_manager,
            max_concurrent=deps.max_concurrent,
        )
        self.requests: dict[str, dict[str, Any]] = {}
        self.grievances: dict[str, dict[str, Any]] = {}
        self.id_generator: IdGenerator = IdGenerator()
        self.repo: TypedStoreRepository[dict[str, Any]] = self.store_repo("dsr", dict)

    def start(self) -> None:
        """Load persisted DSR / grievance records when the service starts."""
        super().start()
        loaded = self.repo.load(default={})
        if loaded:
            self.requests = loaded.get("requests", {})
            self.grievances = loaded.get("grievances", {})

    def handle(self, event: Message) -> None:
        """Process DSR and grievance events.

        Args:
            event: The incoming domain event.
        """
        if event.event_type == Type.DSR_REQUEST:
            self.create_request(event)
        elif event.event_type == Type.GRIEVANCE_LOGGED:
            self.log_grievance(event)

    def create_request(self, event: Message) -> None:
        """Create a new data subject request.

        Args:
            event: The DSR_REQUEST event containing user_id, request_type,
                and optional details.
        """
        user_id: str = event.payload.get("user_id", "")
        request_type: str = event.payload.get("request_type", "")
        if not user_id or request_type not in ("access", "correction", "erasure"):
            logger.warning("dsr.request missing or invalid fields")
            return
        request_id = f"dsr_{user_id}_{self.id_generator.next()}"
        now = datetime.now(timezone.utc)
        with self.state_lock:
            self.requests[request_id] = {
                "request_id": request_id,
                "user_id": user_id,
                "request_type": request_type,
                "status": "pending",
                "requested_at": now.isoformat(),
                "due_by": (now + timedelta(days=self.response_days)).isoformat(),
                "details": event.payload.get("details", ""),
            }
            self.repo.save(
                {
                    "requests": self.requests,
                    "grievances": self.grievances,
                }
            )
            self.emit(
                Type.DSR_REQUESTED,
                {
                    "request_id": request_id,
                    "user_id": user_id,
                    "request_type": request_type,
                },
                correlation_id=event.correlation_id,
            )

    def log_grievance(self, event: Message) -> None:
        """Log a new grievance.

        Args:
            event: The GRIEVANCE_LOGGED event containing user_id, subject,
                and optional description.
        """
        user_id: str = event.payload.get("user_id", "")
        subject: str = event.payload.get("subject", "")
        if not user_id or not subject:
            logger.warning("grievance.logged missing user_id or subject")
            return
        grievance_id = f"gr_{user_id}_{self.id_generator.next()}"
        now = datetime.now(timezone.utc)
        with self.state_lock:
            self.grievances[grievance_id] = {
                "grievance_id": grievance_id,
                "user_id": user_id,
                "subject": subject,
                "description": event.payload.get("description", ""),
                "status": "open",
                "logged_at": now.isoformat(),
                "due_by": (now + timedelta(days=self.grievance_days)).isoformat(),
            }
            self.repo.save(
                {
                    "requests": self.requests,
                    "grievances": self.grievances,
                }
            )

    def fulfill_request(self, request_id: str) -> None:
        """Mark a DSR request as fulfilled.

        Args:
            request_id: The request identifier.
        """
        with self.state_lock:
            req = self.requests.get(request_id)
            if req and req.get("status") == "pending":
                req["status"] = "fulfilled"
                req["fulfilled_at"] = datetime.now(timezone.utc).isoformat()
                self.repo.save(
                    {
                        "requests": self.requests,
                        "grievances": self.grievances,
                    }
                )
                self.emit(
                    Type.DSR_FULFILLED,
                    {
                        "request_id": request_id,
                        "user_id": req["user_id"],
                        "request_type": req["request_type"],
                    },
                )

    def reject_request(self, request_id: str, reason: str) -> None:
        """Reject a DSR request with a reason.

        Args:
            request_id: The request identifier.
            reason: Reason for rejection.
        """
        with self.state_lock:
            req = self.requests.get(request_id)
            if req and req.get("status") == "pending":
                req["status"] = "rejected"
                req["rejected_at"] = datetime.now(timezone.utc).isoformat()
                req["rejection_reason"] = reason
                self.repo.save(
                    {
                        "requests": self.requests,
                        "grievances": self.grievances,
                    }
                )
                self.emit(
                    Type.DSR_REJECTED,
                    {
                        "request_id": request_id,
                        "user_id": req["user_id"],
                        "request_type": req["request_type"],
                        "reason": reason,
                    },
                )

    def resolve_grievance(self, grievance_id: str, resolution: str) -> None:
        """Resolve a grievance with a resolution note.

        Args:
            grievance_id: The grievance identifier.
            resolution: Resolution description.
        """
        with self.state_lock:
            gr = self.grievances.get(grievance_id)
            if gr and gr.get("status") == "open":
                gr["status"] = "resolved"
                gr["resolution"] = resolution
                gr["resolved_at"] = datetime.now(timezone.utc).isoformat()
                self.repo.save(
                    {
                        "requests": self.requests,
                        "grievances": self.grievances,
                    }
                )
                self.emit(
                    Type.GRIEVANCE_RESOLVED,
                    {
                        "grievance_id": grievance_id,
                        "user_id": gr["user_id"],
                        "resolution": resolution,
                    },
                )

    def get_requests(self, user_id: str) -> list[dict[str, Any]]:
        """Return all DSR requests for a user.

        Args:
            user_id: The user identifier.

        Returns:
            List of request records.
        """
        with self.state_lock:
            return [r for r in self.requests.values() if r.get("user_id") == user_id]

    def get_grievances(self, user_id: str) -> list[dict[str, Any]]:
        """Return all grievances for a user.

        Args:
            user_id: The user identifier.

        Returns:
            List of grievance records.
        """
        with self.state_lock:
            return [g for g in self.grievances.values() if g.get("user_id") == user_id]
