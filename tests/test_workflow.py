"""Exhaustive tests for WorkflowService."""
from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.workflow.service import WorkflowService


class TestWorkflowService:

    def test_start_creates_workflow(self) -> None:
        svc = WorkflowService(service_id="workflow")
        svc.handle(
            Event(event_type="workflow.start",
                  source="test",
                  payload={
                      "type": "origination",
                      "entity_id": "app_1"
                  }))
        rec = svc.store.get("workflow:app_1")
        assert rec["type"] == "origination"
        assert rec["current_stage"] == "created"
        assert rec["status"] == "active"

    def test_start_emits_workflow_started(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.WORKFLOW_STARTED, lambda e: received.append(e))
        svc = WorkflowService(service_id="workflow", bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="workflow.start",
                  source="test",
                  payload={
                      "type": "recovery",
                      "entity_id": "loan_1"
                  }))
        assert len(received) == 1
        assert received[0].payload["workflow_type"] == "recovery"

    def test_rejects_empty_type(self) -> None:
        svc = WorkflowService(service_id="workflow")
        svc.handle(
            Event(event_type="workflow.start",
                  source="test",
                  payload={
                      "type": "",
                      "entity_id": "x"
                  }))
        assert len(svc.store.keys("workflow:")) == 0

    def test_rejects_empty_entity_id(self) -> None:
        svc = WorkflowService(service_id="workflow")
        svc.handle(
            Event(event_type="workflow.start",
                  source="test",
                  payload={
                      "type": "origination",
                      "entity_id": ""
                  }))
        assert len(svc.store.keys("workflow:")) == 0

    def test_advance_moves_to_next_stage(self) -> None:
        svc = WorkflowService(service_id="workflow")
        svc.handle(
            Event(event_type="workflow.start",
                  source="test",
                  payload={
                      "type": "origination",
                      "entity_id": "app_2"
                  }))
        svc.handle(
            Event(event_type="workflow.advance",
                  source="test",
                  payload={"entity_id": "app_2"}))
        rec = svc.store.get("workflow:app_2")
        assert rec["current_stage"] == "kyc_pending"
        assert rec["stage_index"] == 1

    def test_advance_completes_workflow(self) -> None:
        svc = WorkflowService(service_id="workflow")
        svc.handle(
            Event(event_type="workflow.start",
                  source="test",
                  payload={
                      "type": "origination",
                      "entity_id": "app_3"
                  }))
        for _ in range(6):
            svc.handle(
                Event(event_type="workflow.advance",
                      source="test",
                      payload={"entity_id": "app_3"}))
        rec = svc.store.get("workflow:app_3")
        assert rec["status"] == "completed"
        assert "completed_at" in rec

    def test_advance_completed_emits_workflow_completed(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.WORKFLOW_COMPLETED,
                      lambda e: received.append(e))
        svc = WorkflowService(service_id="workflow", bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="workflow.start",
                  source="test",
                  payload={
                      "type": "origination",
                      "entity_id": "app_4"
                  }))
        for _ in range(6):
            svc.handle(
                Event(event_type="workflow.advance",
                      source="test",
                      payload={"entity_id": "app_4"}))
        assert len(received) == 1

    def test_advance_unknown_entity_noop(self) -> None:
        svc = WorkflowService(service_id="workflow")
        svc.handle(
            Event(event_type="workflow.advance",
                  source="test",
                  payload={"entity_id": "NONEXISTENT"}))

    def test_auto_starts_on_origination_submitted(self) -> None:
        svc = WorkflowService(service_id="workflow")
        svc.handle(
            Event(event_type=EventType.ORIGINATION_SUBMITTED,
                  source="test",
                  payload={"application_id": "app_5"}))
        rec = svc.store.get("workflow:app_5")
        assert rec is not None
        assert rec["type"] == "origination"

    def test_auto_advances_on_underwriter_approved(self) -> None:
        svc = WorkflowService(service_id="workflow")
        svc.handle(
            Event(event_type=EventType.ORIGINATION_SUBMITTED,
                  source="test",
                  payload={"application_id": "app_6"}))
        svc.handle(
            Event(event_type=EventType.UNDERWRITER_APPROVED,
                  source="test",
                  payload={"application_id": "app_6"}))
        rec = svc.store.get("workflow:app_6")
        assert rec["current_stage"] == "kyc_pending"

    def test_ignores_unrelated_events(self) -> None:
        svc = WorkflowService(service_id="workflow")
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        assert len(svc.store.keys("workflow:")) == 0

    def test_multiple_workflows_independent(self) -> None:
        svc = WorkflowService(service_id="workflow")
        svc.handle(
            Event(event_type="workflow.start",
                  source="test",
                  payload={
                      "type": "origination",
                      "entity_id": "a"
                  }))
        svc.handle(
            Event(event_type="workflow.start",
                  source="test",
                  payload={
                      "type": "recovery",
                      "entity_id": "b"
                  }))
        assert svc.store.get("workflow:a")["type"] == "origination"
        assert svc.store.get("workflow:b")["type"] == "recovery"
