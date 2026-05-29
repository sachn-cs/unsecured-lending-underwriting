"""Saga orchestration — distributed transaction coordination.

Each saga step has a forward action and a compensating rollback action.
If any step fails, all previous steps are rolled back in reverse order.
"""

from __future__ import annotations

__all__ = [
    "Saga",
    "SagaOrchestrator",
    "SagaStep",
]

import logging
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from underwrite.__events__ import Event
from underwrite.__exceptions__ import ProtocolError
from underwrite.__store__ import MemoryStore, Store

logger = logging.getLogger(__name__)


class _Emitter(Protocol):
    """Protocol for saga event emitters (typically a NanoService)."""

    def emit(self,
             event_type: str,
             payload: dict[str, Any],
             correlation_id: str = "") -> Event:
        ...


@dataclass
class SagaStep:
    """One step in a saga — forward action and compensating rollback."""

    name: str
    forward_event_type: str
    forward_payload: dict[str, Any]
    compensate_event_type: str
    compensate_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "forward_event_type": self.forward_event_type,
            "forward_payload": self.forward_payload,
            "compensate_event_type": self.compensate_event_type,
            "compensate_payload": self.compensate_payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SagaStep:
        return cls(
            name=data["name"],
            forward_event_type=data["forward_event_type"],
            forward_payload=data["forward_payload"],
            compensate_event_type=data["compensate_event_type"],
            compensate_payload=data["compensate_payload"],
        )


@dataclass
class Saga:
    """Runtime state for an in-flight saga transaction."""

    saga_id: str
    name: str
    steps: list[SagaStep] = field(default_factory=list)
    completed_steps: list[int] = field(default_factory=list)
    status: str = "started"
    error: str = ""
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "saga_id": self.saga_id,
            "name": self.name,
            "steps": [s.to_dict() for s in self.steps],
            "completed_steps": self.completed_steps,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Saga:
        return cls(
            saga_id=data["saga_id"],
            name=data["name"],
            steps=[SagaStep.from_dict(s) for s in data.get("steps", [])],
            completed_steps=list(data.get("completed_steps", [])),
            status=data.get("status", "started"),
            error=data.get("error", ""),
            started_at=data.get("started_at", ""),
        )

    def validate(self) -> None:
        """Validate step order integrity.

        Raises:
            ProtocolError: If steps have gaps, duplicates, or out-of-range indices.
        """
        if not self.steps:
            raise ProtocolError(f"saga {self.saga_id} has no steps")
        total = len(self.steps)
        seen: set[int] = set()
        for i, idx in enumerate(self.completed_steps):
            if idx < 0 or idx >= total:
                raise ProtocolError(
                    f"saga {self.saga_id} completed_step {idx} out of range [0, {total})"
                )
            if idx in seen:
                raise ProtocolError(
                    f"saga {self.saga_id} duplicate completed_step {idx}")
            seen.add(idx)
            if i > 0 and idx <= self.completed_steps[i - 1]:
                raise ProtocolError(
                    f"saga {self.saga_id} completed_steps not strictly increasing "
                    f"({self.completed_steps[i - 1]} >= {idx})")


class SagaOrchestrator:
    """Coordinates saga execution with rollback on failure.

    Persists saga state to the provided *store* on every mutation
    so that in-flight sagas survive process restarts.
    """

    def __init__(self, store: Store | None = None) -> None:
        self.__lock: threading.RLock = threading.RLock()
        self.__sagas: dict[str, Saga] = {}
        self.__emitters: dict[str, _Emitter] = {}
        self.__store: Store = store or MemoryStore()
        self.__load_sagas()

    def __saga_store_key(self, saga_id: str) -> str:
        return f"saga:{saga_id}"

    def __load_sagas(self) -> None:
        """Restore all persisted sagas from the store on startup."""
        try:
            for key in self.__store.keys("saga:", limit=10000):
                raw = self.__store.get(key)
                if raw is not None and isinstance(raw, dict):
                    saga = Saga.from_dict(raw)
                    saga.validate()
                    self.__sagas[saga.saga_id] = saga
        except Exception:
            logger.exception("failed to load persisted sagas, starting fresh")

    def __persist_saga(self, saga: Saga) -> None:
        """Write saga state to the store."""
        try:
            self.__store.set(self.__saga_store_key(saga.saga_id),
                             saga.to_dict())
        except Exception:
            logger.exception("failed to persist saga %s", saga.saga_id)

    def __remove_saga(self, saga_id: str) -> None:
        """Remove saga from the store."""
        try:
            self.__store.delete(self.__saga_store_key(saga_id))
        except Exception:
            logger.exception("failed to remove saga %s from store", saga_id)

    def register_emitter(self, saga_name: str, emitter: _Emitter) -> None:
        """Registers an event emitter (NanoService) for a saga type."""
        with self.__lock:
            self.__emitters[saga_name] = emitter

    def start_saga(self, name: str, steps: list[SagaStep]) -> str:
        """Creates and stores a new saga, returning its unique ID.

        Args:
            name: Logical saga name (e.g. ``"loan_origination"``).
            steps: Ordered list of saga steps to execute.

        Returns:
            The generated saga ID.

        Raises:
            ProtocolError: If *steps* is empty.
        """
        if not steps:
            raise ProtocolError("saga must have at least one step")
        saga = Saga(saga_id=str(uuid.uuid4()), name=name, steps=steps)
        with self.__lock:
            self.__sagas[saga.saga_id] = saga
            self.__persist_saga(saga)
        return saga.saga_id

    def __step_idempotency_key(self, saga_id: str, step_index: int) -> str:
        return f"saga_step:{saga_id}:{step_index}"

    def execute_step(self, saga_id: str, step_index: int) -> bool:
        """Executes a single saga step and rolls back on failure.

        Checks idempotency via the store — if ``saga_step:{saga_id}:{step_index}``
        already exists the step is considered already completed and skipped.
        This guarantees safe replay after a crash.

        Args:
            saga_id: Target saga ID.
            step_index: Index of the step to execute.

        Returns:
            ``True`` if the step succeeded, ``False`` otherwise.
        """
        idem_key = self.__step_idempotency_key(saga_id, step_index)
        if self.__store.get(idem_key) is not None:
            logger.debug(
                "saga %s step %d already completed (idempotency), skipping",
                saga_id, step_index)
            return True
        with self.__lock:
            saga = self.__sagas.get(saga_id)
            if not saga or saga.status != "started":
                logger.warning("saga %s not found or not started (status=%s)",
                               saga_id, saga.status if saga else "N/A")
                return False
            if step_index >= len(saga.steps):
                logger.warning(
                    "saga %s step_index %d out of range (total steps %d)",
                    saga_id, step_index, len(saga.steps))
                return False
            step = saga.steps[step_index]
            emitter = self.__emitters.get(saga.name)
            if not emitter:
                logger.warning("saga %s no emitter registered for saga type %r",
                               saga_id, saga.name)
                return False
            try:
                emitter.emit(step.forward_event_type, step.forward_payload)
                if saga_id in self.__sagas:
                    self.__sagas[saga_id].completed_steps.append(step_index)
                self.__store.set(idem_key, True)
                if saga_id in self.__sagas:
                    self.__persist_saga(self.__sagas[saga_id])
                return True
            except Exception as exc:
                tb = traceback.format_exc()
                logger.exception("saga %s step %d (%s) failed", saga_id,
                                 step_index, step.name)
                self.__rollback(saga_id, step_index, f"{exc}\n{tb}")
                return False

    def execute_all(self, saga_id: str) -> bool:
        """Executes all steps of a saga sequentially.

        If any step fails, previously completed steps are rolled back.

        Args:
            saga_id: Target saga ID.

        Returns:
            ``True`` if all steps completed, ``False`` on failure.
        """
        with self.__lock:
            saga = self.__sagas.get(saga_id)
            if not saga:
                logger.warning("execute_all: saga %s not found", saga_id)
                return False
        for i in range(len(saga.steps)):
            if not self.execute_step(saga_id, i):
                return False
        with self.__lock:
            if saga_id in self.__sagas:
                self.__sagas[saga_id].status = "completed"
                self.__persist_saga(self.__sagas[saga_id])
        return True

    def __rollback(self, saga_id: str, failed_step: int, error: str) -> None:
        with self.__lock:
            saga = self.__sagas.get(saga_id)
            if not saga:
                logger.warning("rollback: saga %s not found", saga_id)
                return
            saga.status = "compensating"
            saga.error = error
            steps_to_rollback = list(saga.completed_steps)
        emitter = self.__emitters.get(saga.name)
        if not emitter:
            logger.warning("rollback: no emitter for saga %s type %r", saga_id,
                           saga.name)
            return
        compensation_errors: list[str] = []
        for idx in reversed(steps_to_rollback):
            step = saga.steps[idx]
            try:
                emitter.emit(step.compensate_event_type,
                             step.compensate_payload)
            except Exception as exc:
                compensation_errors.append(
                    f"compensation step {step.name} failed: {exc}")
                logger.exception("saga %s compensation step %s failed: %s",
                                 saga_id, step.name, exc)
        with self.__lock:
            if saga_id in self.__sagas:
                s = self.__sagas[saga_id]
                s.status = "rolled_back"
                if compensation_errors:
                    s.error += "; " + "; ".join(compensation_errors)
                self.__persist_saga(s)

    def get_saga(self, saga_id: str) -> Saga | None:
        """Returns a copy of the saga state, or ``None`` if not found.

        The returned ``Saga`` is a deep copy; mutations to it do not
        affect the orchestrator's internal state.
        """
        with self.__lock:
            saga = self.__sagas.get(saga_id)
            if saga is None:
                return None
            return Saga.from_dict(saga.to_dict())

    def replay_saga(self, saga_id: str) -> bool:
        """Replays an incomplete saga from its last completed step.

        Finds the next unexecuted step after the last completed step
        and executes all remaining steps.  Useful for crash recovery.

        Args:
            saga_id: Target saga ID.

        Returns:
            ``True`` if all remaining steps completed, ``False`` on
            failure (the saga is rolled back by ``execute_all``).
        """
        with self.__lock:
            saga = self.__sagas.get(saga_id)
            if not saga:
                logger.warning("replay_saga: saga %s not found", saga_id)
                return False
            if saga.status == "completed":
                return True
            if saga.status == "rolled_back":
                logger.warning(
                    "replay_saga: saga %s is rolled back, cannot replay",
                    saga_id)
                return False
            # Determine the next step after the last completed one
            completed = set(saga.completed_steps)
            next_idx = -1
            for i in range(len(saga.steps)):
                if i not in completed:
                    next_idx = i
                    break
        # Execute all steps starting from next_idx
        if next_idx < 0:
            return True  # all steps already completed
        from_index = next_idx
        with self.__lock:
            saga_ref = self.__sagas.get(saga_id)
            if not saga_ref:
                return False
        # Call execute_all if starting from step 0, else execute remaining
        if from_index == 0:
            return self.execute_all(saga_id)
        for i in range(from_index, len(saga.steps)):
            if not self.execute_step(saga_id, i):
                return False
        with self.__lock:
            if saga_id in self.__sagas:
                self.__sagas[saga_id].status = "completed"
                self.__persist_saga(self.__sagas[saga_id])
        return True
