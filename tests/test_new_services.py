"""Tests for new stub services: underwriter, pricing, document, disbursement, collection, settlement."""

from __future__ import annotations

from underwrite.__events__ import Event
from underwrite.services.collection.service import CollectionService
from underwrite.services.disbursement.service import DisbursementService
from underwrite.services.document.service import DocumentService
from underwrite.services.pricing.service import PricingService
from underwrite.services.settlement.service import SettlementService
from underwrite.services.underwriter.service import UnderwriterService


def test_underwriter_handle_does_not_crash() -> None:
    svc = UnderwriterService(service_id="underwriter")
    svc.handle(Event(event_type="test", source="test", payload={}))
    assert svc.is_running is False


def test_pricing_handle_does_not_crash() -> None:
    svc = PricingService(service_id="pricing")
    svc.handle(Event(event_type="test", source="test", payload={}))
    assert svc.is_running is False


def test_document_handle_does_not_crash() -> None:
    svc = DocumentService(service_id="document")
    svc.handle(Event(event_type="test", source="test", payload={}))
    assert svc.is_running is False


def test_disbursement_handle_does_not_crash() -> None:
    svc = DisbursementService(service_id="disbursement")
    svc.handle(Event(event_type="test", source="test", payload={}))
    assert svc.is_running is False


def test_collection_handle_does_not_crash() -> None:
    svc = CollectionService(service_id="collection")
    svc.handle(Event(event_type="test", source="test", payload={}))
    assert svc.is_running is False


def test_settlement_handle_does_not_crash() -> None:
    svc = SettlementService(service_id="settlement")
    svc.handle(Event(event_type="test", source="test", payload={}))
    assert svc.is_running is False
