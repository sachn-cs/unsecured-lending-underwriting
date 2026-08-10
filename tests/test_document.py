# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Handler — loan document generation."""

from __future__ import annotations

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.document.handler import Handler
from underwrite.services.document.handler import Handler as DocumentHandler
from underwrite.store import InMemory


def svc(bus=None) -> Handler:
    return DocumentHandler(name="document", bus=bus or LocalBus(), store=InMemory())


class TestDocumentService:
    def test_generates_doc_on_approval(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.DOCUMENT_GENERATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Message(
                event_type=Type.UNDERWRITER_APPROVED,
                source="test",
                payload={"borrower": "alice", "principal": 10000},
            )
        )
        assert len(received) == 1
        assert received[0].payload["borrower"] == "alice"
        assert "doc_id" in received[0].payload

    def test_stores_document_record(self) -> None:
        svc_inst = svc()
        svc_inst.handle(
            Message(
                event_type=Type.UNDERWRITER_APPROVED,
                source="test",
                payload={"borrower": "bob", "principal": 20000},
            )
        )
        docs = svc_inst.documents_for("bob")
        assert len(docs) == 1
        assert docs[0]["principal"] == 20000.0

    def test_multiple_documents_for_same_borrower(self) -> None:
        svc_inst = svc()
        for i in range(3):
            svc_inst.handle(
                Message(
                    event_type=Type.UNDERWRITER_APPROVED,
                    source="test",
                    payload={"borrower": "carol", "principal": 10000 * (i + 1)},
                )
            )
        assert len(svc_inst.documents_for("carol")) == 3

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.DOCUMENT_GENERATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(Message(event_type="seed.added", source="test", payload={}))
        assert len(received) == 0

    def test_empty_borrower_returns_empty_list(self) -> None:
        svc_inst = svc()
        assert svc_inst.documents_for("ghost") == []
