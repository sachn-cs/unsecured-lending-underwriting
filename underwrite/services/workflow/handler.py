"""Workflow orchestration service.

Coordinates multi-step business processes by tracking state machines.
Each workflow instance progresses through stages and emits
``workflow.started`` / ``workflow.completed`` events.
"""

from __future__ import annotations

from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.message import Message, Type
from underwrite.metrics import Collector, SystemClock
from underwrite.saga import Orchestrator
from underwrite.services.base import StatefulService
from underwrite.store import Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer

STAGES: dict[str, list[str]] = {
    "origination": [
        "created",
        "kyc_pending",
        "risk_review",
        "underwriting",
        "approved",
        "disbursed",
    ],
    "recovery": ["started", "contact_made", "negotiation", "settlement", "closed"],
    "default": [
        "noticed",
        "npa_classified",
        "collateral_review",
        "recovery",
        "chargeoff",
    ],
}


class Handler(StatefulService):
    """Manages business process state machines for origination, recovery, etc."""

    def __init__(
        self,
        name: str,
        bus: EventBus,
        store: Store,
        identity: Keypair | None = None,
        metrics: Collector | None = None,
        health: Checks | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: Orchestrator | None = None,
        supervisor: Watcher | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
    ) -> None:
        super().__init__(
            name=name,
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
        self.handlers: dict[str, Any] = {
            Type.WORKFLOW_START: self.__on_workflow_start,
            Type.WORKFLOW_ADVANCE: self.__on_workflow_advance,
            Type.ORIGINATION_SUBMITTED: self.__on_origination_submitted,
            Type.UNDERWRITER_APPROVED: self.__on_underwriter_approved,
        }

    def handle(self, event: Message) -> None:
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def __on_workflow_start(self, event: Message) -> None:
        """Start a new workflow instance.

        Args:
            event: The WORKFLOW_START event.
        """
        self.__start_workflow(
            event.payload.get("type", ""),
            event.payload.get("entity_id", ""),
            event.correlation_id,
        )

    def __on_workflow_advance(self, event: Message) -> None:
        """Advance a workflow to the next stage.

        Args:
            event: The WORKFLOW_ADVANCE event.
        """
        self.__advance_workflow(
            event.payload.get("entity_id", ""),
            event.correlation_id,
        )

    def __on_origination_submitted(self, event: Message) -> None:
        """Start an origination workflow when an application is submitted.

        Args:
            event: The ORIGINATION_SUBMITTED event.
        """
        entity_id = event.payload.get("application_id", "")
        if entity_id and not self.store.get(f"workflow:{entity_id}"):
            self.__start_workflow("origination", entity_id, event.correlation_id)

    def __on_underwriter_approved(self, event: Message) -> None:
        """Advance the workflow when underwriter approves.

        Args:
            event: The UNDERWRITER_APPROVED event.
        """
        entity_id = event.payload.get("application_id", "")
        if entity_id:
            self.__advance_workflow(entity_id, event.correlation_id)

    def __start_workflow(self, workflow_type: str, entity_id: str, correlation_id: str = "") -> None:
        """Start a new workflow in the store and emit WORKFLOW_STARTED.

        Args:
            workflow_type: The workflow type identifier.
            entity_id: The entity the workflow tracks.
            correlation_id: Correlation ID for emitted events.
        """
        if not workflow_type or not entity_id:
            return
        stages = STAGES.get(workflow_type, ["started"])
        self.store.set(
            f"workflow:{entity_id}",
            {
                "type": workflow_type,
                "entity_id": entity_id,
                "current_stage": stages[0],
                "stages": stages,
                "stage_index": 0,
                "status": "active",
                "started_at": self.__clock.iso(),
            },
        )
        self.emit(
            Type.WORKFLOW_STARTED,
            {
                "workflow_type": workflow_type,
                "entity_id": entity_id,
                "stage": stages[0],
            },
            correlation_id=correlation_id,
        )

    def __advance_workflow(self, entity_id: str, correlation_id: str = "") -> None:
        """Advance a workflow to the next stage or complete it.

        Args:
            entity_id: The entity identifier.
            correlation_id: Correlation ID for emitted events.
        """
        if not entity_id:
            return
        with self.state_lock:
            record = self.store.get(f"workflow:{entity_id}")
            if not record or record.get("status") != "active":
                return
            next_idx: int = record["stage_index"] + 1
            if next_idx >= len(record["stages"]):
                record["status"] = "completed"
                record["completed_at"] = self.__clock.iso()
                self.store.set(f"workflow:{entity_id}", record)
            else:
                record["stage_index"] = next_idx
                record["current_stage"] = record["stages"][next_idx]
                self.store.set(f"workflow:{entity_id}", record)
        if record["status"] == "completed":
            self.emit(
                Type.WORKFLOW_COMPLETED,
                {
                    "workflow_type": record["type"],
                    "entity_id": entity_id,
                },
                correlation_id=correlation_id,
            )
