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

logger = logging.getLogger("underwrite")


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


class SagaOrchestrator:
    """Coordinates saga execution with rollback on failure."""

    def __init__(self) -> None:
        self.__lock: threading.RLock = threading.RLock()
        self.__sagas: dict[str, Saga] = {}
        self.__emitters: dict[str, _Emitter] = {}

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
        """
        saga = Saga(saga_id=str(uuid.uuid4()), name=name, steps=steps)
        with self.__lock:
            self.__sagas[saga.saga_id] = saga
        return saga.saga_id

    def execute_step(self, saga_id: str, step_index: int) -> bool:
        """Executes a single saga step and rolls back on failure.

        Args:
            saga_id: Target saga ID.
            step_index: Index of the step to execute.

        Returns:
            ``True`` if the step succeeded, ``False`` otherwise.
        """
        with self.__lock:
            saga = self.__sagas.get(saga_id)
            if not saga or saga.status != "started":
                return False
            if step_index >= len(saga.steps):
                return False
            step = saga.steps[step_index]
            emitter = self.__emitters.get(saga.name)
            if not emitter:
                return False
            try:
                emitter.emit(step.forward_event_type, step.forward_payload)
                if saga_id in self.__sagas:
                    self.__sagas[saga_id].completed_steps.append(step_index)
                return True
            except Exception as exc:
                tb = traceback.format_exc()
                logger.exception("saga %s step %d (%s) failed",
                                 saga_id, step_index, step.name)
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
                return False
        for i in range(len(saga.steps)):
            if not self.execute_step(saga_id, i):
                return False
        with self.__lock:
            if saga_id in self.__sagas:
                self.__sagas[saga_id].status = "completed"
        return True

    def __rollback(self, saga_id: str, failed_step: int, error: str) -> None:
        with self.__lock:
            saga = self.__sagas.get(saga_id)
            if not saga:
                return
            saga.status = "compensating"
            saga.error = error
            steps_to_rollback = list(saga.completed_steps)
        emitter = self.__emitters.get(saga.name)
        if not emitter:
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

    def get_saga(self, saga_id: str) -> Saga | None:
        """Returns the saga state, or ``None`` if not found."""
        with self.__lock:
            return self.__sagas.get(saga_id)
