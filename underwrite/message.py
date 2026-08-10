"""Domain events shared across all nano services."""

from __future__ import annotations

__all__ = [
    "Message",
    "Type",
    "MAX_PAYLOAD_SIZE",
]

import enum
import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Any

from underwrite.constants import MAX_PAYLOAD_KEYS
from underwrite.keypair import Keypair
from underwrite.logger import logger

MAX_PAYLOAD_SIZE: int = 1_000_000


@dataclass(frozen=True, slots=True)
class Message:
    """Standard event envelope for all nano-service communication.

    Every event carries a unique identifier, a correlation chain for
    tracing, and a cryptographic signature from the emitting service's
    identity.  Downstream consumers use this to verify provenance.

    Payloads are validated against *MAX_PAYLOAD_SIZE* (1 MB) at
    construction to prevent oversized events from entering the bus.
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    source: str = ""
    source_key: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    signature: str = ""
    trace_id: str = ""
    parent_span_id: str = ""

    def __post_init__(self) -> None:
        payload_size: int = 0
        if len(self.payload) > MAX_PAYLOAD_KEYS:
            from underwrite.exceptions import ProtocolError

            raise ProtocolError(f"event payload has too many keys ({len(self.payload)} > {MAX_PAYLOAD_KEYS})")
        try:
            import json as json_mod

            payload_str = json_mod.dumps(self.payload, default=str)
            payload_size = len(payload_str.encode("utf-8"))
        except (TypeError, ValueError):
            payload_size = MAX_PAYLOAD_SIZE + 1
        if payload_size > MAX_PAYLOAD_SIZE:
            from underwrite.exceptions import ProtocolError

            raise ProtocolError(f"event payload exceeds MAX_PAYLOAD_SIZE ({payload_size} > {MAX_PAYLOAD_SIZE})")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for f in fields(self):
            result[f.name] = getattr(self, f.name)
        return result

    def canonical_sign_bytes(self) -> bytes:
        """Returns the canonical byte sequence to sign/verify this event.

        The payload is JSON-serialised with sorted keys so the signature
        is stable across dict iteration order. The source is included so
        an attacker holding one trusted key cannot re-stamp events under
        another service id.
        """
        import json as _json

        payload_str = _json.dumps(self.payload, sort_keys=True, default=str)
        canonical = f"{self.event_id}|{self.timestamp}|{self.event_type}|{self.source}|{payload_str}"
        return canonical.encode("utf-8")

    @classmethod
    def signed(
        cls,
        keypair: Keypair,
        *,
        type: str,
        source: str,
        source_key: str = "",
        payload: dict[str, Any] | None = None,
        correlation_id: str = "",
        trace_id: str = "",
        parent_span_id: str = "",
    ) -> Message:
        """Construct a Message and sign it with *keypair* in one step.

        Returns:
            A new Message with the signature field populated.
        """
        payload = payload if payload is not None else {}
        msg = cls(
            event_type=type,
            source=source,
            source_key=source_key or keypair.public_key,
            payload=payload,
            correlation_id=correlation_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
        )
        signature = keypair.sign(msg.canonical_sign_bytes().decode("utf-8"))
        # signature is already a str (hex) from Keypair.sign
        return cls(
            event_id=msg.event_id,
            event_type=msg.event_type,
            source=msg.source,
            source_key=msg.source_key,
            timestamp=msg.timestamp,
            payload=msg.payload,
            correlation_id=msg.correlation_id,
            trace_id=msg.trace_id,
            parent_span_id=msg.parent_span_id,
            signature=signature,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        known = {f.name for f in fields(cls)}
        extra = set(data) - known
        if extra:
            logger.warning("Message.from_dict dropping unknown field(s): {}", sorted(extra))
        return cls(**{k: data[k] for k in known if k in data})


class Type(str, enum.Enum):
    """Central registry of all event types in the underwrite system.

    Convention: ``<domain>.<action>[.<outcome>]``.
    Use ``Type.XXX.value`` to get the bare string where needed.
    """

    SEED_ADDED = "seed.added"
    USER_ADDED = "user.added"
    LOAN_ORIGINATED = "loan.originated"
    REPAID = "repaid"
    DEFAULT_OCCURRED = "default.occurred"
    REVOKED = "revoked"

    QUOTE = "quote"
    QUOTE_CALCULATED = "quote.calculated"
    PRICING_COMPUTED = "pricing.computed"
    PRICING_REQUEST = "pricing.request"

    KYC_VERIFIED = "kyc.verified"
    KYC_REJECTED = "kyc.rejected"
    AML_CLEARED = "aml.cleared"
    AML_FROZEN = "aml.frozen"

    FRAUD_ALERT = "fraud.alert"
    WASH_FLAG = "fraud.wash.flag"
    VELOCITY_FLAG = "fraud.velocity.flag"

    RISK_SCORED = "risk.scored"
    RISK_EARLY_WARNING = "risk.early_warning"

    NPA_BUCKET_CHANGED = "npa.bucket.changed"
    DLG_TRIGGERED = "npa.dlg.triggered"
    SMA_CLASSIFIED = "sma.classified"
    PROVISIONING_COMPUTED = "provisioning.computed"
    INCOME_RECOGNITION_SUSPENDED = "income_recognition.suspended"

    COLLATERAL_MARKED = "collateral.marked"
    COLLATERAL_LIQUIDATED = "collateral.liquidated"

    GOVERNANCE_PROPOSAL = "governance.proposal"
    GOVERNANCE_EXECUTED = "governance.executed"

    RECOVERY_STARTED = "recovery.started"
    RECOVERY_COMPLETED = "recovery.completed"

    IDENTITY_REGISTERED = "identity.registered"
    IDENTITY_ROTATED = "identity.rotated"
    IDENTITY_REGISTER = "identity.register"
    IDENTITY_ROTATE = "identity.rotate"

    NOTIFICATION_SENT = "notification.sent"

    REPORT_GENERATED = "report.generated"

    UNDERWRITER_APPROVED = "underwriter.approved"
    UNDERWRITER_REJECTED = "underwriter.rejected"
    UNDERWRITE_REQUEST = "underwrite.request"
    UNDERWRITER_CONDITIONAL_APPROVED = "underwriter.conditional_approved"
    UNDERWRITER_REVIEW = "underwriter.review"
    UNDERWRITER_ESCALATED = "underwriter.escalated"
    UNDERWRITE_RULE_VIOLATED = "underwrite.rule.violated"

    DOCUMENT_GENERATED = "document.generated"

    DISBURSEMENT_PROCESSED = "disbursement.processed"

    COLLECTION_UPDATED = "collection.updated"

    SETTLEMENT_COMPLETED = "settlement.completed"

    ORIGINATION_CREATED = "origination.created"
    ORIGINATION_SUBMITTED = "origination.submitted"
    ORIGINATION_CREATE = "origination.create"
    ORIGINATION_SUBMIT = "origination.submit"

    SERVICING_STARTED = "servicing.started"

    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_DUE = "payment.due"
    PAYMENT_OVERDUE = "payment.overdue"
    PAYMENT_RECEIVE = "payment.receive"
    PAYMENT_SCHEDULE = "payment.schedule"
    PAYMENT_CHECK_OVERDUE = "payment.check_overdue"

    FEE_ASSESSED = "fee.assessed"
    FEE_ASSESS = "fee.assess"
    FEE_PAY = "fee.pay"
    PENAL_INTEREST_ASSESSED = "penal_interest.assessed"

    PREPAYMENT_REQUEST = "prepayment.request"
    PREPAYMENT_PROCESSED = "prepayment.processed"
    FORECLOSURE_COMPUTED = "foreclosure.computed"

    KFS_GENERATE = "kfs.generate"
    KFS_GENERATED = "kfs.generated"

    RAZORPAY_ORDER_CREATE = "razorpay.order.create"
    RAZORPAY_ORDER_CREATED = "razorpay.order.created"
    RAZORPAY_SUBSCRIBE = "razorpay.subscribe"
    RAZORPAY_SUBSCRIPTION_CREATED = "razorpay.subscription.created"
    RAZORPAY_PAYMENT_CAPTURED = "razorpay.payment.captured"
    RAZORPAY_PAYMENT_FAILED = "razorpay.payment.failed"
    RAZORPAY_PAYMENT_REFUNDED = "razorpay.payment.refunded"
    RAZORPAY_SUBSCRIPTION_CHARGED = "razorpay.subscription.charged"
    RAZORPAY_SUBSCRIPTION_FAILED = "razorpay.subscription.failed"
    RAZORPAY_MANDATE_ACTIVE = "razorpay.mandate.active"
    RAZORPAY_MANDATE_INACTIVE = "razorpay.mandate.inactive"
    RAZORPAY_WEBHOOK_RECEIVED = "razorpay.webhook.received"

    CONSENT_RECORDED = "consent.recorded"
    CONSENT_WITHDRAWN = "consent.withdrawn"
    CONSENT_EXPIRED = "consent.expired"
    DSR_REQUEST = "dsr.request"
    DSR_REQUESTED = "dsr.requested"
    DSR_FULFILLED = "dsr.fulfilled"
    DSR_REJECTED = "dsr.rejected"
    GRIEVANCE_LOGGED = "grievance.logged"
    GRIEVANCE_RESOLVED = "grievance.resolved"
    BREACH_DETECTED = "breach.detected"
    BREACH_NOTIFIED = "breach.notified"
    BREACH_CLOSED = "breach.closed"
    DATA_PURGED = "data.purged"
    DATA_ARCHIVED = "data.archived"

    STATEMENT_GENERATED = "statement.generated"
    STATEMENT_GENERATE = "statement.generate"

    COMMUNICATION_SENT = "communication.sent"
    COMMUNICATION_SEND = "communication.send"

    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_START = "workflow.start"
    WORKFLOW_ADVANCE = "workflow.advance"

    DECISION_MADE = "decision.made"
    DECISION_EVALUATE = "decision.evaluate"

    GRAPH_PATH = "graph_path"
    GRAPH_CREDIT_LIMIT = "graph_credit_limit"
    GRAPH_USERS = "graph_users"
    GRAPH_PATH_RESULT = "graph_path_result"
    GRAPH_CREDIT_LIMIT_RESULT = "graph_credit_limit_result"
    GRAPH_USERS_RESULT = "graph_users_result"

    MECHANISM_REJECTED = "mechanism.rejected"

    SAGA_STARTED = "saga.started"
    SAGA_COMPLETED = "saga.completed"
    SAGA_ROLLED_BACK = "saga.rolled_back"
    SAGA_COMPENSATE = "saga.compensate"

    CREDIT_BUREAU_CHECK = "credit_bureau.check"
    CREDIT_BUREAU_CHECKED = "credit_bureau.checked"
    CREDIT_BUREAU_CHECK_FAILED = "credit_bureau.check_failed"

    CKYC_VERIFY = "ckyc.verify"
    CKYC_VERIFIED = "ckyc.verified"
    CKYC_REJECTED = "ckyc.rejected"

    DUPLICATE_DROPPED = "idempotency.duplicate_dropped"

    AML_FLAGGED = "aml.flagged"
    KYC_VIDEO_INITIATED = "kyc.video_initiated"
    KYC_VIDEO_VERIFIED = "kyc.video_verified"
    PRICING_PENAL_INTEREST = "pricing.penal_interest"
    PRICING_PENAL_INTEREST_COMPUTED = "pricing.penal_interest_computed"
    PRICING_FORECLOSURE = "pricing.foreclosure"
    PRICING_FORECLOSURE_COMPUTED = "pricing.foreclosure_computed"
    RECOVERY_OFFER = "recovery.offer"
    RECOVERY_OFFER_RESPONSE = "recovery.offer_response"
    RECOVERY_ESCALATED = "recovery.escalated"
    RECOVERY_PROGRESS = "recovery.progress"
