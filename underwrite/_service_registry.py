"""Service registry constants — maps service names to module/class paths.

Separated from ``__runtime__.py`` so the registry is testable without
instantiating the full Runtime.
"""

from __future__ import annotations

from underwrite.__events__ import EventType

__all__ = [
    "SERVICE_CLASSES",
    "SERVICE_MAP",
    "WIRING",
]

# Maps service name -> (module_path, class_name)
SERVICE_MAP: dict[str, str] = {
    "mechanism": "underwrite.services.mechanism.service",
    "audit": "underwrite.services.audit.service",
    "quote": "underwrite.services.quote.service",
    "risk": "underwrite.services.risk.service",
    "fraud": "underwrite.services.fraud.service",
    "compliance": "underwrite.services.compliance.service",
    "npa": "underwrite.services.npa.service",
    "collateral": "underwrite.services.collateral.service",
    "recovery": "underwrite.services.recovery.service",
    "governance": "underwrite.services.governance.service",
    "graph": "underwrite.services.graph.service",
    "identity": "underwrite.services.identity.service",
    "notification": "underwrite.services.notification.service",
    "reporting": "underwrite.services.reporting.service",
    "underwriter": "underwrite.services.underwriter.service",
    "pricing": "underwrite.services.pricing.service",
    "document": "underwrite.services.document.service",
    "disbursement": "underwrite.services.disbursement.service",
    "collection": "underwrite.services.collection.service",
    "settlement": "underwrite.services.settlement.service",
    "origination": "underwrite.services.origination.service",
    "servicing": "underwrite.services.servicing.service",
    "payment": "underwrite.services.payment.service",
    "communication": "underwrite.services.communication.service",
    "workflow": "underwrite.services.workflow.service",
    "decision": "underwrite.services.decision.service",
    "fee": "underwrite.services.fee.service",
    "statement": "underwrite.services.statement.service",
}

SERVICE_CLASSES: dict[str, str] = {
    "mechanism": "MechanismService",
    "audit": "AuditService",
    "quote": "QuoteService",
    "risk": "RiskService",
    "fraud": "FraudService",
    "compliance": "ComplianceService",
    "npa": "NPAService",
    "collateral": "CollateralService",
    "recovery": "RecoveryService",
    "governance": "GovernanceService",
    "graph": "GraphService",
    "identity": "IdentityService",
    "notification": "NotificationService",
    "reporting": "ReportingService",
    "underwriter": "UnderwriterService",
    "pricing": "PricingService",
    "document": "DocumentService",
    "disbursement": "DisbursementService",
    "collection": "CollectionService",
    "settlement": "SettlementService",
    "origination": "OriginationService",
    "servicing": "ServicingService",
    "payment": "PaymentService",
    "communication": "CommunicationService",
    "workflow": "WorkflowService",
    "decision": "DecisionService",
    "fee": "FeeService",
    "statement": "StatementService",
}

WIRING: dict[str, list[str]] = {
    EventType.SEED_ADDED.value: ["audit", "origination"],
    EventType.USER_ADDED.value: [
        "audit", "fraud", "compliance", "risk", "origination"
    ],
    EventType.LOAN_ORIGINATED.value: [
        "audit", "fraud", "risk", "npa", "collateral", "collection",
        "servicing", "payment", "fee"
    ],
    EventType.REPAID.value: [
        "audit", "fraud", "collection", "payment", "servicing"
    ],
    EventType.DEFAULT_OCCURRED.value: [
        "audit", "npa", "collateral", "recovery", "settlement", "workflow"
    ],
    EventType.REVOKED.value: ["audit", "graph"],
    EventType.QUOTE_CALCULATED.value: ["audit", "pricing"],
    EventType.KYC_VERIFIED.value: ["audit", "compliance", "workflow"],
    EventType.KYC_REJECTED.value: [
        "audit", "compliance", "notification", "workflow"
    ],
    EventType.AML_CLEARED.value: ["audit", "compliance"],
    EventType.AML_FROZEN.value: ["audit", "compliance", "notification"],
    EventType.FRAUD_ALERT.value: ["audit", "notification", "decision"],
    EventType.WASH_FLAG.value: ["audit", "notification", "decision"],
    EventType.VELOCITY_FLAG.value: ["audit", "notification", "decision"],
    EventType.RISK_SCORED.value: ["audit", "underwriter", "decision"],
    EventType.RISK_EARLY_WARNING.value: ["audit", "notification", "servicing"],
    EventType.NPA_BUCKET_CHANGED.value: ["audit", "notification", "collection"],
    EventType.DLG_TRIGGERED.value: ["audit", "notification", "recovery"],
    EventType.COLLATERAL_MARKED.value: ["audit"],
    EventType.COLLATERAL_LIQUIDATED.value: ["audit", "settlement"],
    EventType.GOVERNANCE_PROPOSAL.value: ["governance"],
    EventType.GOVERNANCE_EXECUTED.value: ["audit", "governance"],
    EventType.RECOVERY_STARTED.value: ["audit", "workflow"],
    EventType.RECOVERY_COMPLETED.value: ["audit", "settlement"],
    EventType.IDENTITY_REGISTERED.value: ["audit", "identity"],
    EventType.IDENTITY_ROTATED.value: ["audit", "identity"],
    EventType.NOTIFICATION_SENT.value: ["audit", "communication"],
    EventType.REPORT_GENERATED.value: ["audit", "reporting"],
    EventType.UNDERWRITER_APPROVED.value: [
        "audit", "document", "disbursement", "workflow"
    ],
    EventType.UNDERWRITER_REJECTED.value: ["audit", "notification", "workflow"],
    EventType.PRICING_COMPUTED.value: ["audit", "quote", "document"],
    EventType.DOCUMENT_GENERATED.value: [
        "audit", "disbursement", "communication"
    ],
    EventType.DISBURSEMENT_PROCESSED.value: ["audit", "servicing"],
    EventType.COLLECTION_UPDATED.value: ["audit", "statement", "fee"],
    EventType.SETTLEMENT_COMPLETED.value: ["audit", "servicing", "reporting"],
    EventType.ORIGINATION_CREATED.value: ["audit", "underwriter", "workflow"],
    EventType.ORIGINATION_SUBMITTED.value: [
        "audit", "risk", "fraud", "compliance"
    ],
    EventType.PAYMENT_RECEIVED.value: [
        "audit", "collection", "servicing", "statement"
    ],
    EventType.PAYMENT_DUE.value: ["audit", "notification", "communication"],
    EventType.PAYMENT_OVERDUE.value: [
        "audit", "collection", "fee", "notification"
    ],
    EventType.FEE_ASSESSED.value: ["audit", "statement"],
    EventType.STATEMENT_GENERATED.value: ["audit", "communication"],
    EventType.WORKFLOW_STARTED.value: ["audit"],
    EventType.WORKFLOW_COMPLETED.value: ["audit", "notification"],
    EventType.DECISION_MADE.value: ["audit", "underwriter", "workflow"],
}
