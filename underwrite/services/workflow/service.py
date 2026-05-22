"""Workflow orchestration service.

Coordinates multi-step business processes by tracking state machines.
Each workflow instance progresses through stages and emits
``workflow.started`` / ``workflow.completed`` events.
"""

from __future__ import annotations

from datetime import datetime, timezone

from underwrite.__events__ import Event, EventType
from underwrite.services.base import NanoService

STAGES: dict[str, list[str]] = {
    "origination": [
        "created", "kyc_pending", "risk_review", "underwriting", "approved",
        "disbursed"
    ],
    "recovery": [
        "started", "contact_made", "negotiation", "settlement", "closed"
    ],
    "default": [
        "noticed", "npa_classified", "collateral_review", "recovery",
        "chargeoff"
    ],
}


class WorkflowService(NanoService):
    """Manages business process state machines for origination, recovery, etc."""

    def handle(self, event: Event) -> None:
        if event.event_type == "workflow.start":
            self.__start_workflow(
                event.payload.get("type", ""),
                event.payload.get("entity_id", ""),
                event.correlation_id,
            )

        elif event.event_type == "workflow.advance":
            self.__advance_workflow(
                event.payload.get("entity_id", ""),
                event.correlation_id,
            )

        elif event.event_type == EventType.ORIGINATION_SUBMITTED:
            entity_id = event.payload.get("application_id", "")
            if entity_id and not self.store.get(f"workflow:{entity_id}"):
                self.__start_workflow("origination", entity_id,
                                      event.correlation_id)

        elif event.event_type == EventType.UNDERWRITER_APPROVED:
            entity_id = event.payload.get("application_id", "")
            if entity_id:
                self.__advance_workflow(entity_id, event.correlation_id)

    def __start_workflow(self,
                         workflow_type: str,
                         entity_id: str,
                         correlation_id: str = "") -> None:
        if not workflow_type or not entity_id:
            return
        stages = STAGES.get(workflow_type, ["started"])
        self.store.set(
            f"workflow:{entity_id}", {
                "type": workflow_type,
                "entity_id": entity_id,
                "current_stage": stages[0],
                "stages": stages,
                "stage_index": 0,
                "status": "active",
                "started_at": datetime.now(timezone.utc).isoformat(),
            })
        self.emit(EventType.WORKFLOW_STARTED, {
            "workflow_type": workflow_type,
            "entity_id": entity_id,
            "stage": stages[0],
        },
                  correlation_id=correlation_id)

    def __advance_workflow(self,
                           entity_id: str,
                           correlation_id: str = "") -> None:
        if not entity_id:
            return
        record = self.store.get(f"workflow:{entity_id}")
        if not record or record.get("status") != "active":
            return
        next_idx: int = record["stage_index"] + 1
        if next_idx >= len(record["stages"]):
            record["status"] = "completed"
            record["completed_at"] = datetime.now(timezone.utc).isoformat()
            self.store.set(f"workflow:{entity_id}", record)
            self.emit(EventType.WORKFLOW_COMPLETED, {
                "workflow_type": record["type"],
                "entity_id": entity_id,
            },
                      correlation_id=correlation_id)
        else:
            record["stage_index"] = next_idx
            record["current_stage"] = record["stages"][next_idx]
            self.store.set(f"workflow:{entity_id}", record)
