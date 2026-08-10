# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Exhaustive tests for Handler."""

from __future__ import annotations

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.workflow import Handler as WorkflowHandler
from underwrite.store import InMemory


class TestWorkflowService:
    def test_start_creates_workflow(self) -> None:
        svc = WorkflowHandler(name="workflow", bus=LocalBus(), store=InMemory())
        svc.handle(
            Message(event_type="workflow.start", source="test", payload={"type": "origination", "entity_id": "app_1"})
        )
        rec = svc.store.get("workflow:app_1")
        assert rec is not None
        assert rec["type"] == "origination"
        assert rec["current_stage"] == "created"
        assert rec["status"] == "active"

    def test_start_emits_workflow_started(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.WORKFLOW_STARTED, lambda e: received.append(e))
        svc = WorkflowHandler(name="workflow", bus=bus, store=InMemory())
        bus.start()
        svc.handle(
            Message(event_type="workflow.start", source="test", payload={"type": "recovery", "entity_id": "loan_1"})
        )
        assert len(received) == 1
        assert received[0].payload["workflow_type"] == "recovery"

    def test_rejects_empty_type(self) -> None:
        svc = WorkflowHandler(name="workflow", bus=LocalBus(), store=InMemory())
        svc.handle(Message(event_type="workflow.start", source="test", payload={"type": "", "entity_id": "x"}))
        assert len(svc.store.keys("workflow:")) == 0

    def test_rejects_empty_entity_id(self) -> None:
        svc = WorkflowHandler(name="workflow", bus=LocalBus(), store=InMemory())
        svc.handle(
            Message(event_type="workflow.start", source="test", payload={"type": "origination", "entity_id": ""})
        )
        assert len(svc.store.keys("workflow:")) == 0

    def test_advance_moves_to_next_stage(self) -> None:
        svc = WorkflowHandler(name="workflow", bus=LocalBus(), store=InMemory())
        svc.handle(
            Message(event_type="workflow.start", source="test", payload={"type": "origination", "entity_id": "app_2"})
        )
        svc.handle(Message(event_type="workflow.advance", source="test", payload={"entity_id": "app_2"}))
        rec = svc.store.get("workflow:app_2")
        assert rec is not None
        assert rec["current_stage"] == "kyc_pending"
        assert rec["stage_index"] == 1

    def test_advance_completes_workflow(self) -> None:
        svc = WorkflowHandler(name="workflow", bus=LocalBus(), store=InMemory())
        svc.handle(
            Message(event_type="workflow.start", source="test", payload={"type": "origination", "entity_id": "app_3"})
        )
        for _ in range(6):
            svc.handle(Message(event_type="workflow.advance", source="test", payload={"entity_id": "app_3"}))
        rec = svc.store.get("workflow:app_3")
        assert rec is not None
        assert rec["status"] == "completed"
        assert "completed_at" in rec

    def test_advance_completed_emits_workflow_completed(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.WORKFLOW_COMPLETED, lambda e: received.append(e))
        svc = WorkflowHandler(name="workflow", bus=bus, store=InMemory())
        bus.start()
        svc.handle(
            Message(event_type="workflow.start", source="test", payload={"type": "origination", "entity_id": "app_4"})
        )
        for _ in range(6):
            svc.handle(Message(event_type="workflow.advance", source="test", payload={"entity_id": "app_4"}))
        assert len(received) == 1

    def test_advance_unknown_entity_noop(self) -> None:
        svc = WorkflowHandler(name="workflow", bus=LocalBus(), store=InMemory())
        svc.handle(Message(event_type="workflow.advance", source="test", payload={"entity_id": "NONEXISTENT"}))

    def test_auto_starts_on_origination_submitted(self) -> None:
        svc = WorkflowHandler(name="workflow", bus=LocalBus(), store=InMemory())
        svc.handle(Message(event_type=Type.ORIGINATION_SUBMITTED, source="test", payload={"application_id": "app_5"}))
        rec = svc.store.get("workflow:app_5")
        assert rec is not None
        assert rec["type"] == "origination"

    def test_auto_advances_on_underwriter_approved(self) -> None:
        svc = WorkflowHandler(name="workflow", bus=LocalBus(), store=InMemory())
        svc.handle(Message(event_type=Type.ORIGINATION_SUBMITTED, source="test", payload={"application_id": "app_6"}))
        svc.handle(Message(event_type=Type.UNDERWRITER_APPROVED, source="test", payload={"application_id": "app_6"}))
        rec = svc.store.get("workflow:app_6")
        assert rec is not None
        assert rec["current_stage"] == "kyc_pending"

    def test_ignores_unrelated_events(self) -> None:
        svc = WorkflowHandler(name="workflow", bus=LocalBus(), store=InMemory())
        svc.handle(Message(event_type="seed.added", source="test", payload={}))
        assert len(svc.store.keys("workflow:")) == 0

    def test_multiple_workflows_independent(self) -> None:
        svc = WorkflowHandler(name="workflow", bus=LocalBus(), store=InMemory())
        svc.handle(
            Message(event_type="workflow.start", source="test", payload={"type": "origination", "entity_id": "a"})
        )
        svc.handle(Message(event_type="workflow.start", source="test", payload={"type": "recovery", "entity_id": "b"}))
        rec_a = svc.store.get("workflow:a")
        assert rec_a is not None
        assert rec_a["type"] == "origination"
        rec_b = svc.store.get("workflow:b")
        assert rec_b is not None
        assert rec_b["type"] == "recovery"
