"""Pricing — RBI-compliant interest rate and fee computation.

Computes interest rates, fees, and all-in-cost APR per RBI Master
Direction on Non-Banking Financial Company — Fair Practices Code
(RBI/2021-22/95). Enforces rate caps, penal interest limits, and
transparent fee disclosure for Indian retail lending.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from underwrite.__authz__ import AccessControl
from underwrite.__bus__ import EventBus
from underwrite.__constants__ import DAYS_PER_YEAR
from underwrite.__events__ import Event, EventType
from underwrite.__exceptions__ import ProtocolError
from underwrite.__health__ import HealthRegistry
from underwrite.__identity__ import Identity
from underwrite.__metrics__ import MetricsCollector
from underwrite.__saga__ import SagaOrchestrator
from underwrite.__store__ import Store
from underwrite.__supervisor__ import ServiceSupervisor
from underwrite.__tracer__ import Tracer
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_empty

BASE_RATE: float = 0.08
RISK_PREMIUM_MULTIPLIER: float = 0.50
HOME_LOAN_CAP: float = 0.12
GOLD_LOAN_CAP: float = 0.18
PERSONAL_LOAN_CAP: float = 0.28
MICRO_LOAN_CAP: float = 0.30
DEFAULT_LOAN_CAP: float = 0.30
PENAL_INTEREST_CAP: float = 0.24
MIN_PRINCIPAL_FOR_CAP: float = 50000.0
DEFAULT_PROBABILITY_FALLBACK: float = 0.02
GST_RATE: float = 0.18
MICRO_LOAN_PRINCIPAL_THRESHOLD: float = 10_000.0
MICRO_LOAN_PROCESSING_FEE_CAP: float = 5_000.0
MICRO_LOAN_PROCESSING_FEE_RATE: float = 0.0025
HIGH_RISK_ORIGINATION_FEE_RATE: float = 0.05
LOW_RISK_ORIGINATION_FEE_RATE: float = 0.04
APPR_TOLERANCE: float = 1e-10
RATE_QUANTUM: Decimal = Decimal("0.01")
MAX_NEWTON_ITERATIONS: int = 100


@dataclass(frozen=True, slots=True)
class LoanTypePolicy:
    """Per-loan-type pricing policy.

    Each loan product registers one of these to participate in
    pricing without modifying compute_rate_cap / origination_fee_pct /
    processing_fee / foreclosure_charge_pct. New loan types extend
    the registry rather than edit existing dispatch code (OCP).
    """

    name: str
    rate_cap: float
    origination_fee_rate: float
    foreclosure_charge_rate: float


@dataclass(frozen=True, slots=True)
class PricingConfig:
    """Typed configuration for PricingHandler.

    Replaces the previous ``kwargs.pop("rate_cap", ...)`` pattern:
    callers now pass a PricingConfig (or its fields are extracted
    from kwargs via a constructor that does not mutate the caller's
    mapping).
    """

    rate_cap: float = DEFAULT_LOAN_CAP
    penal_interest_cap: float = PENAL_INTEREST_CAP


_LOAN_TYPE_POLICIES: dict[str, LoanTypePolicy] = {
    "home": LoanTypePolicy(
        name="home",
        rate_cap=HOME_LOAN_CAP,
        origination_fee_rate=0.005,
        foreclosure_charge_rate=0.0,
    ),
    "gold": LoanTypePolicy(
        name="gold",
        rate_cap=GOLD_LOAN_CAP,
        origination_fee_rate=0.008,
        foreclosure_charge_rate=0.0,
    ),
    "personal": LoanTypePolicy(
        name="personal",
        rate_cap=PERSONAL_LOAN_CAP,
        origination_fee_rate=0.01,
        foreclosure_charge_rate=HIGH_RISK_ORIGINATION_FEE_RATE,
    ),
    "micro": LoanTypePolicy(
        name="micro",
        rate_cap=MICRO_LOAN_CAP,
        origination_fee_rate=0.02,
        foreclosure_charge_rate=HIGH_RISK_ORIGINATION_FEE_RATE,
    ),
}


def register_loan_type(policy: LoanTypePolicy) -> None:
    """Register or replace a loan-type policy at runtime."""
    _LOAN_TYPE_POLICIES[policy.name] = policy


def _policy_for(loan_type: str) -> LoanTypePolicy:
    return _LOAN_TYPE_POLICIES.get(loan_type) or LoanTypePolicy(
        name=loan_type,
        rate_cap=DEFAULT_LOAN_CAP,
        origination_fee_rate=LOW_RISK_ORIGINATION_FEE_RATE,
        foreclosure_charge_rate=LOW_RISK_ORIGINATION_FEE_RATE,
    )


def compute_rate_cap(principal: float, loan_type: str = "personal") -> float:
    """Compute the maximum permissible interest rate for a loan.

    Args:
        principal: Loan principal amount.
        loan_type: Type of loan (home, gold, personal, micro).

    Returns:
        Maximum annual interest rate cap.
    """
    if principal < MIN_PRINCIPAL_FOR_CAP:
        return MICRO_LOAN_CAP
    return _policy_for(loan_type).rate_cap


class PricingHandler(NanoService):
    """Computes loan pricing with RBI-mandated rate caps and fee disclosure."""

    def __init__(
        self,
        service_id: str,
        bus: EventBus,
        store: Store,
        identity: Identity | None = None,
        metrics: MetricsCollector | None = None,
        health: HealthRegistry | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: SagaOrchestrator | None = None,
        supervisor: ServiceSupervisor | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize the pricing service.

        Args:
            rate_cap: Maximum permissible interest rate.
            penal_interest_cap: Maximum penal interest rate.
        """
        config = PricingConfig(
            rate_cap=kwargs.get("rate_cap", DEFAULT_LOAN_CAP),
            penal_interest_cap=kwargs.get("penal_interest_cap", PENAL_INTEREST_CAP),
        )
        super().__init__(
            service_id=service_id,
            identity=identity,
            bus=bus,
            store=store,
            metrics=metrics,
            health=health,
            authz=authz,
            tracer=tracer,
            saga=saga,
            supervisor=supervisor,
            secrets_manager=secrets_manager,
            max_concurrent=max_concurrent,
        )
        self.__rate_cap: float = config.rate_cap
        self.__penal_interest_cap: float = config.penal_interest_cap
        self.handlers: dict[str, Any] = {
            EventType.PRICING_REQUEST: self.compute_pricing,
            "pricing.penal_interest": self.compute_penal_interest,
            "pricing.foreclosure": self.compute_foreclosure,
        }

    def handle(self, event: Event) -> None:
        """Dispatch an event to the appropriate handler.

        Args:
            event: The incoming domain event.
        """
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def compute_pricing(self, event: Event) -> None:
        """Compute loan pricing including interest rate, fees, and APR.

        Args:
            event: The PRICING_REQUEST event.
        """
        p = event.payload
        borrower: str = get_non_empty(p, "borrower", "")
        principal: float = get_finite(p, "principal", 0.0)
        dp: float = get_finite(p, "default_probability", DEFAULT_PROBABILITY_FALLBACK)
        tenure_months: int = int(get_finite(p, "tenure_months", 12))
        loan_type: str = p.get("loan_type", "personal")
        credit_score: int = int(get_finite(p, "credit_score", 0))
        annual_income: float = get_finite(p, "annual_income", 0.0)

        risk_premium: float = dp * RISK_PREMIUM_MULTIPLIER
        interest_rate: float = BASE_RATE + risk_premium

        rate_cap = compute_rate_cap(principal, loan_type)
        if interest_rate > rate_cap:
            raise ProtocolError(
                f"interest_rate {interest_rate * 100:.2f}% exceeds {loan_type} cap of {rate_cap * 100:.2f}% (RBI)"
            )

        origination_fee_pct = self.origination_fee_pct(principal, loan_type)
        origination_fee: float = principal * origination_fee_pct
        processing_fee: float = self.processing_fee(principal)
        gst_on_fees: float = round((origination_fee + processing_fee) * GST_RATE, 2)
        total_upfront_fees: float = origination_fee + processing_fee + gst_on_fees

        monthly_rate = interest_rate / 12.0
        emi_dec: Decimal = self.compute_emi(principal, monthly_rate, tenure_months)
        emi: float = float(emi_dec)
        total_repayment = emi_dec * Decimal(tenure_months)
        total_interest = total_repayment - Decimal(str(principal))
        apr = self.compute_apr(principal, tenure_months, interest_rate, processing_fees=total_upfront_fees)

        result: dict[str, Any] = {
            "borrower": borrower,
            "principal": principal,
            "interest_rate": round(interest_rate, 4),
            "annual_percentage_rate": round(apr, 4),
            "tenure_months": tenure_months,
            "emi_amount": emi,
            "total_interest_payable": float(total_interest),
            "total_repayment": float(total_repayment),
            "origination_fee": round(origination_fee, 2),
            "origination_fee_pct": origination_fee_pct,
            "processing_fee": round(processing_fee, 2),
            "gst_on_fees": gst_on_fees,
            "total_upfront_fees": round(total_upfront_fees, 2),
            "risk_premium": round(risk_premium, 4),
            "rate_cap_applied": interest_rate >= rate_cap,
            "loan_type": loan_type,
            "penal_interest_annual_rate": self.__penal_interest_cap,
        }

        if credit_score > 0:
            result["credit_score"] = credit_score
        if annual_income > 0:
            result["annual_income"] = annual_income
            dti = (emi / annual_income * 12) if annual_income > 0 else 0
            result["debt_to_income_ratio"] = round(dti, 4)

        self.emit(EventType.PRICING_COMPUTED, result, correlation_id=event.correlation_id)

    def compute_penal_interest(self, event: Event) -> None:
        """Compute penal interest on overdue amounts.

        Args:
            event: The pricing.penal_interest event.
        """
        p = event.payload
        borrower: str = get_non_empty(p, "borrower", "")
        overdue_amount: float = get_finite(p, "overdue_amount", 0.0)
        overdue_days: int = int(get_finite(p, "overdue_days", 0))

        daily_penal_rate = self.__penal_interest_cap / float(DAYS_PER_YEAR)
        penal_amount = overdue_amount * daily_penal_rate * overdue_days

        self.emit(
            "pricing.penal_interest_computed",
            {
                "borrower": borrower,
                "overdue_amount": overdue_amount,
                "overdue_days": overdue_days,
                "penal_interest_rate": self.__penal_interest_cap,
                "penal_interest_amount": round(penal_amount, 2),
            },
            correlation_id=event.correlation_id,
        )

    def compute_foreclosure(self, event: Event) -> None:
        """Compute foreclosure charges for a loan.

        Args:
            event: The pricing.foreclosure event.
        """
        p = event.payload
        borrower: str = get_non_empty(p, "borrower", "")
        outstanding_principal: float = get_finite(p, "outstanding_principal", 0.0)
        loan_type: str = p.get("loan_type", "personal")

        foreclosure_charge_pct = self.foreclosure_charge_pct(loan_type)
        foreclosure_amount = outstanding_principal * foreclosure_charge_pct
        total_due = outstanding_principal + foreclosure_amount

        self.emit(
            "pricing.foreclosure_computed",
            {
                "borrower": borrower,
                "outstanding_principal": outstanding_principal,
                "foreclosure_charge_pct": foreclosure_charge_pct,
                "foreclosure_charge": round(foreclosure_amount, 2),
                "total_due": round(total_due, 2),
            },
            correlation_id=event.correlation_id,
        )

    def origination_fee_pct(self, principal: float, loan_type: str) -> float:
        """Return the origination fee percentage based on loan type.

        Args:
            principal: Loan principal amount.
            loan_type: Type of loan.

        Returns:
            Origination fee as a decimal fraction.
        """
        policy = _policy_for(loan_type)
        if loan_type == "micro":
            return 0.02 if principal < MICRO_LOAN_PRINCIPAL_THRESHOLD else 0.015
        return policy.origination_fee_rate

    def processing_fee(self, principal: float) -> float:
        """Compute the processing fee for a loan.

        Args:
            principal: Loan principal amount.

        Returns:
            Processing fee amount.
        """
        if principal <= MICRO_LOAN_PRINCIPAL_THRESHOLD:
            return 0.0
        return min(principal * MICRO_LOAN_PROCESSING_FEE_RATE, MICRO_LOAN_PROCESSING_FEE_CAP)

    def foreclosure_charge_pct(self, loan_type: str) -> float:
        """Return the foreclosure charge percentage based on loan type.

        Args:
            loan_type: Type of loan.

        Returns:
            Foreclosure charge as a decimal fraction.
        """
        return _policy_for(loan_type).foreclosure_charge_rate

    @staticmethod
    def compute_emi(principal: float, monthly_rate: float, tenure_months: int) -> Decimal:
        """Compute the equated monthly installment.

        Args:
            principal: Loan principal amount.
            monthly_rate: Monthly interest rate (annual / 12).
            tenure_months: Loan tenure in months.

        Returns:
            EMI amount as a Decimal. Computed with Decimal arithmetic
            to avoid float precision loss for long tenures.
        """
        p = Decimal(str(principal))
        r = Decimal(str(monthly_rate))
        n = Decimal(tenure_months)
        if r <= 0 or n <= 0:
            return p / max(n, Decimal("1"))
        factor = (Decimal("1") + r) ** n
        return (p * r * factor / (factor - Decimal("1"))).quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)

    @staticmethod
    def validate_interest_rate(rate: float, loan_type: str = "personal") -> float:
        """Validate interest rate against RBI regulatory caps.

        Args:
            rate: Annual interest rate as decimal.
            loan_type: One of 'personal', 'home', 'gold', 'micro', 'education', 'vehicle'.

        Returns:
            The validated rate.

        Raises:
            ProtocolError: If rate exceeds regulatory cap.
        """
        cap = compute_rate_cap(0.0, loan_type)
        if rate > cap:
            raise ProtocolError(f"Interest rate {rate * 100:.2f}% exceeds {loan_type} loan cap of {cap * 100:.2f}%")
        return rate

    def compute_apr(
        self,
        principal: float,
        term_months: int,
        interest_rate: float,
        processing_fees: float = 0.0,
        insurance_premium: float = 0.0,
        other_charges: float = 0.0,
    ) -> float:
        """Compute APR including all fees per RBI Fair Practices Code.

        Uses the Newton-Raphson method to solve for APR where:
        PV = sum(Pmt / (1+APR/12)^t) for t=1..term_months
        net_disbursed = principal - processing_fees - insurance_premium - other_charges

        Args:
            principal: Loan principal amount.
            term_months: Loan tenure in months.
            interest_rate: Annual interest rate as decimal (e.g. 0.12 for 12%).
            processing_fees: Processing fees deducted upfront.
            insurance_premium: Insurance premium deducted upfront.
            other_charges: Other charges deducted upfront.

        Returns:
            APR as a decimal (e.g. 0.15 for 15% APR).
        """
        net_disbursed = principal - processing_fees - insurance_premium - other_charges
        if net_disbursed <= 0:
            return 0.0
        monthly_rate = interest_rate / 12.0
        emi = principal * monthly_rate * (1 + monthly_rate) ** term_months / ((1 + monthly_rate) ** term_months - 1)

        apr_guess = interest_rate
        for _ in range(MAX_NEWTON_ITERATIONS):
            monthly_apr = apr_guess / 12.0
            pv = 0.0
            dpv = 0.0
            for t in range(1, term_months + 1):
                factor = (1 + monthly_apr) ** t
                pv += emi / factor
                dpv -= t * emi / (factor * (1 + monthly_apr))
            diff = pv - net_disbursed
            if abs(diff) < APPR_TOLERANCE:
                break
            apr_guess -= diff / dpv
        return max(0.0, apr_guess)
