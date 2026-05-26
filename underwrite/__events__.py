"""Domain events shared across all nano services."""

from __future__ import annotations

__all__ = [
    "Event",
    "EventType",
]

import enum
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


class EventType(str, enum.Enum):
    """Central registry of all event types in the underwrite system.

    Convention: ``<domain>.<action>[.<outcome>]``.
    Use ``EventType.XXX.value`` to get the bare string where needed.
    """

    # Core
    SEED_ADDED = "seed.added"
    USER_ADDED = "user.added"
    LOAN_ORIGINATED = "loan.originated"
    REPAID = "repaid"
    DEFAULT_OCCURRED = "default.occurred"
    REVOKED = "revoked"

    # Quote & pricing
    QUOTE_CALCULATED = "quote.calculated"
    PRICING_COMPUTED = "pricing.computed"
    PRICING_REQUEST = "pricing.request"

    # KYC / AML
    KYC_VERIFIED = "kyc.verified"
    KYC_REJECTED = "kyc.rejected"
    AML_CLEARED = "aml.cleared"
    AML_FROZEN = "aml.frozen"

    # Fraud
    FRAUD_ALERT = "fraud.alert"
    WASH_FLAG = "fraud.wash.flag"
    VELOCITY_FLAG = "fraud.velocity.flag"

    # Risk
    RISK_SCORED = "risk.scored"
    RISK_EARLY_WARNING = "risk.early_warning"

    # NPA
    NPA_BUCKET_CHANGED = "npa.bucket.changed"
    DLG_TRIGGERED = "npa.dlg.triggered"

    # Collateral
    COLLATERAL_MARKED = "collateral.marked"
    COLLATERAL_LIQUIDATED = "collateral.liquidated"

    # Governance
    GOVERNANCE_PROPOSAL = "governance.proposal"
    GOVERNANCE_EXECUTED = "governance.executed"

    # Recovery
    RECOVERY_STARTED = "recovery.started"
    RECOVERY_COMPLETED = "recovery.completed"

    # Identity
    IDENTITY_REGISTERED = "identity.registered"
    IDENTITY_ROTATED = "identity.rotated"
    IDENTITY_REGISTER = "identity_register"
    IDENTITY_ROTATE = "identity_rotate"

    # Notification
    NOTIFICATION_SENT = "notification.sent"

    # Reporting
    REPORT_GENERATED = "report.generated"

    # Underwriting
    UNDERWRITER_APPROVED = "underwriter.approved"
    UNDERWRITER_REJECTED = "underwriter.rejected"
    UNDERWRITE_REQUEST = "underwrite.request"

    # Document
    DOCUMENT_GENERATED = "document.generated"

    # Disbursement
    DISBURSEMENT_PROCESSED = "disbursement.processed"

    # Collection
    COLLECTION_UPDATED = "collection.updated"

    # Settlement
    SETTLEMENT_COMPLETED = "settlement.completed"

    # Origination
    ORIGINATION_CREATED = "origination.created"
    ORIGINATION_SUBMITTED = "origination.submitted"
    ORIGINATION_CREATE = "origination.create"
    ORIGINATION_SUBMIT = "origination.submit"

    # Servicing
    SERVICING_STARTED = "servicing.started"

    # Payment
    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_DUE = "payment.due"
    PAYMENT_OVERDUE = "payment.overdue"
    PAYMENT_RECEIVE = "payment.receive"
    PAYMENT_SCHEDULE = "payment.schedule"
    PAYMENT_CHECK_OVERDUE = "payment.check_overdue"

    # Fee
    FEE_ASSESSED = "fee.assessed"
    FEE_ASSESS = "fee.assess"
    FEE_PAY = "fee.pay"

    # Statement
    STATEMENT_GENERATED = "statement.generated"
    STATEMENT_GENERATE = "statement.generate"

    # Communication
    COMMUNICATION_SENT = "communication.sent"
    COMMUNICATION_SEND = "communication.send"

    # Workflow
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_START = "workflow.start"
    WORKFLOW_ADVANCE = "workflow.advance"

    # Decision
    DECISION_MADE = "decision.made"
    DECISION_EVALUATE = "decision.evaluate"

    # Graph (internal queries)
    GRAPH_PATH = "graph_path"
    GRAPH_CREDIT_LIMIT = "graph_credit_limit"
    GRAPH_USERS = "graph_users"
    GRAPH_PATH_RESULT = "graph_path_result"
    GRAPH_CREDIT_LIMIT_RESULT = "graph_credit_limit_result"
    GRAPH_USERS_RESULT = "graph_users_result"

    # Mechanism
    MECHANISM_REJECTED = "mechanism.rejected"

    # Saga / compensation
    SAGA_STARTED = "saga.started"
    SAGA_COMPLETED = "saga.completed"
    SAGA_ROLLED_BACK = "saga.rolled_back"
    SAGA_COMPENSATE = "saga.compensate"

    # Idempotency
    DUPLICATE_DROPPED = "idempotency.duplicate_dropped"
