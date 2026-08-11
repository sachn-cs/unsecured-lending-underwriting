# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Handler — DPDPA-compliant DSR and grievance handling."""

from __future__ import annotations

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.dsr import Handler
from underwrite.services.dsr import Handler as DsrHandler
from underwrite.store import Sqlite


def svc(**kw) -> Handler:
    return DsrHandler(name="dsr", bus=LocalBus(), store=Sqlite(":memory:"), **kw)


class TestDsrRequestCreation:
    def test_creates_access_request(self) -> None:
        s = svc()
        s.handle(
            Message(event_type=Type.DSR_REQUEST, source="test", payload={"user_id": "u1", "request_type": "access"})
        )
        reqs = s.get_requests("u1")
        assert len(reqs) == 1
        assert reqs[0]["request_type"] == "access"
        assert reqs[0]["status"] == "pending"

    def test_creates_correction_request(self) -> None:
        s = svc()
        s.handle(
            Message(event_type=Type.DSR_REQUEST, source="test", payload={"user_id": "u2", "request_type": "correction"})
        )
        reqs = s.get_requests("u2")
        assert len(reqs) == 1

    def test_creates_erasure_request(self) -> None:
        s = svc()
        s.handle(
            Message(event_type=Type.DSR_REQUEST, source="test", payload={"user_id": "u3", "request_type": "erasure"})
        )
        reqs = s.get_requests("u3")
        assert len(reqs) == 1

    def test_rejects_invalid_request_type(self) -> None:
        s = svc()
        s.handle(
            Message(
                event_type=Type.DSR_REQUEST,
                source="test",
                payload={"user_id": "u4", "request_type": "invalid_type"},
            )
        )
        assert s.get_requests("u4") == []

    def test_requires_user_id(self) -> None:
        s = svc()
        s.handle(Message(event_type=Type.DSR_REQUEST, source="test", payload={"request_type": "access"}))
        assert s.get_requests("") == []

    def test_emits_dsr_requested_event(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.DSR_REQUESTED, lambda e: received.append(e))
        s = DsrHandler(name="dsr", bus=bus, store=Sqlite(":memory:"))
        bus.start()
        s.handle(
            Message(event_type=Type.DSR_REQUEST, source="test", payload={"user_id": "u5", "request_type": "access"})
        )
        assert len(received) == 1
        assert received[0].payload["request_type"] == "access"


class TestDsrFulfillment:
    def test_fulfill_request(self) -> None:
        s = svc()
        s.handle(
            Message(event_type=Type.DSR_REQUEST, source="test", payload={"user_id": "u10", "request_type": "access"})
        )
        reqs = s.get_requests("u10")
        req_id = reqs[0]["request_id"]
        s.fulfill_request(req_id)
        reqs = s.get_requests("u10")
        assert reqs[0]["status"] == "fulfilled"

    def test_reject_request(self) -> None:
        s = svc()
        s.handle(
            Message(event_type=Type.DSR_REQUEST, source="test", payload={"user_id": "u11", "request_type": "erasure"})
        )
        reqs = s.get_requests("u11")
        req_id = reqs[0]["request_id"]
        s.reject_request(req_id, "legal obligation")
        reqs = s.get_requests("u11")
        assert reqs[0]["status"] == "rejected"
        assert reqs[0]["rejection_reason"] == "legal obligation"

    def test_fulfill_nonexistent_noop(self) -> None:
        s = svc()
        s.fulfill_request("nonexistent")

    def test_double_fulfill_noop(self) -> None:
        s = svc()
        s.handle(
            Message(event_type=Type.DSR_REQUEST, source="test", payload={"user_id": "u12", "request_type": "access"})
        )
        reqs = s.get_requests("u12")
        req_id = reqs[0]["request_id"]
        s.fulfill_request(req_id)
        s.fulfill_request(req_id)
        reqs = s.get_requests("u12")
        assert reqs[0]["status"] == "fulfilled"


class TestGrievance:
    def test_logs_grievance(self) -> None:
        s = svc()
        s.handle(
            Message(
                event_type=Type.GRIEVANCE_LOGGED,
                source="test",
                payload={
                    "user_id": "u20",
                    "subject": "Missing payment credit",
                    "description": "Paid on 1st but not reflected",
                },
            )
        )
        grievances = s.get_grievances("u20")
        assert len(grievances) == 1
        assert grievances[0]["subject"] == "Missing payment credit"
        assert grievances[0]["status"] == "open"

    def test_resolves_grievance(self) -> None:
        s = svc()
        s.handle(
            Message(
                event_type=Type.GRIEVANCE_LOGGED,
                source="test",
                payload={
                    "user_id": "u21",
                    "subject": "Wrong late fee",
                },
            )
        )
        grievances = s.get_grievances("u21")
        gid = grievances[0]["grievance_id"]
        s.resolve_grievance(gid, "Fee waived as goodwill")
        grievances = s.get_grievances("u21")
        assert grievances[0]["status"] == "resolved"
        assert grievances[0]["resolution"] == "Fee waived as goodwill"

    def test_grievance_requires_user_id_and_subject(self) -> None:
        s = svc()
        s.handle(Message(event_type=Type.GRIEVANCE_LOGGED, source="test", payload={"user_id": "u22"}))
        s.handle(Message(event_type=Type.GRIEVANCE_LOGGED, source="test", payload={"subject": "no user"}))
        assert s.get_grievances("u22") == []
        assert s.get_grievances("") == []

    def test_ignores_unrelated_events(self) -> None:
        s = svc()
        s.handle(Message(event_type="seed.added", source="test", payload={}))
        assert s.get_requests("") == []
        assert s.get_grievances("") == []
