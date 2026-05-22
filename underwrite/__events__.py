"""Domain events shared across all nano services."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Event:
    """Standard event envelope for all nano-service communication.

    Every event carries a unique identifier, a correlation chain for
    tracing, and a cryptographic signature from the emitting service's
    identity.  Downstream consumers use this to verify provenance.

    Note: ``payload`` is a mutable dict despite ``frozen=True`` (a
    known dataclass limitation).  Handlers should treat it as read-only.
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    source: str = ""
    source_key: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    signature: str = ""


class EventType:
    """Canonical event type constants.

    Convention: <domain>.<action>[.<outcome>]
    """

    # Core
    SEED_ADDED: str = "seed.added"
    USER_ADDED: str = "user.added"
    LOAN_ORIGINATED: str = "loan.originated"
    REPAID: str = "repaid"
    DEFAULT_OCCURRED: str = "default.occurred"
    REVOKED: str = "revoked"

    # Quote & pricing
    QUOTE_CALCULATED: str = "quote.calculated"
    PRICING_COMPUTED: str = "pricing.computed"

    # KYC / AML
    KYC_VERIFIED: str = "kyc.verified"
    KYC_REJECTED: str = "kyc.rejected"
    AML_CLEARED: str = "aml.cleared"
    AML_FROZEN: str = "aml.frozen"

    # Fraud
    FRAUD_ALERT: str = "fraud.alert"
    WASH_FLAG: str = "fraud.wash.flag"
    VELOCITY_FLAG: str = "fraud.velocity.flag"

    # Risk
    RISK_SCORED: str = "risk.scored"
    RISK_EARLY_WARNING: str = "risk.early_warning"

    # NPA
    NPA_BUCKET_CHANGED: str = "npa.bucket.changed"
    DLG_TRIGGERED: str = "npa.dlg.triggered"

    # Collateral
    COLLATERAL_MARKED: str = "collateral.marked"
    COLLATERAL_LIQUIDATED: str = "collateral.liquidated"

    # Governance
    GOVERNANCE_PROPOSAL: str = "governance.proposal"
    GOVERNANCE_EXECUTED: str = "governance.executed"

    # Recovery
    RECOVERY_STARTED: str = "recovery.started"
    RECOVERY_COMPLETED: str = "recovery.completed"

    # Identity
    IDENTITY_REGISTERED: str = "identity.registered"
    IDENTITY_ROTATED: str = "identity.rotated"

    # Notification
    NOTIFICATION_SENT: str = "notification.sent"

    # Reporting
    REPORT_GENERATED: str = "report.generated"

    # Underwriting
    UNDERWRITER_APPROVED: str = "underwriter.approved"
    UNDERWRITER_REJECTED: str = "underwriter.rejected"

    # Document
    DOCUMENT_GENERATED: str = "document.generated"

    # Disbursement
    DISBURSEMENT_PROCESSED: str = "disbursement.processed"

    # Collection
    COLLECTION_UPDATED: str = "collection.updated"

    # Settlement
    SETTLEMENT_COMPLETED: str = "settlement.completed"

    # Origination
    ORIGINATION_CREATED: str = "origination.created"
    ORIGINATION_SUBMITTED: str = "origination.submitted"

    # Servicing
    SERVICING_STARTED: str = "servicing.started"

    # Payment
    PAYMENT_RECEIVED: str = "payment.received"
    PAYMENT_DUE: str = "payment.due"
    PAYMENT_OVERDUE: str = "payment.overdue"

    # Fee
    FEE_ASSESSED: str = "fee.assessed"

    # Statement
    STATEMENT_GENERATED: str = "statement.generated"

    # Communication
    COMMUNICATION_SENT: str = "communication.sent"

    # Workflow
    WORKFLOW_STARTED: str = "workflow.started"
    WORKFLOW_COMPLETED: str = "workflow.completed"

    # Decision
    DECISION_MADE: str = "decision.made"

    # Saga / compensation
    SAGA_STARTED: str = "saga.started"
    SAGA_COMPLETED: str = "saga.completed"
    SAGA_ROLLED_BACK: str = "saga.rolled_back"
    SAGA_COMPENSATE: str = "saga.compensate"

    # Idempotency
    DUPLICATE_DROPPED: str = "idempotency.duplicate_dropped"
