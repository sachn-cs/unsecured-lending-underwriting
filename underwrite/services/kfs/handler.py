"""Key Fact Statement (KFS) generation service.

Generates Key Fact Statements per RBI Master Direction on KFS
(RBI/2023-24/86, Master Direction DNBR. PD. 008/03.10.119/2023-24).

A KFS includes:
  - Loan amount (principal)
  - Annual Percentage Rate (APR) / effective interest rate
  - Tenure
  - EMI amount with total interest payable
  - Total repayment amount
  - List of all fees and charges
  - Late payment / penal interest terms
  - Foreclosure / prepayment terms
  - Cooling-off / cancellation period
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from underwrite.amortization import AmortizationSchedule, generate_schedule
from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.metrics import Collector, SystemClock
from underwrite.saga import Orchestrator
from underwrite.services.base import Core
from underwrite.store import Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator

DEFAULT_COOLING_OFF_DAYS = 3


def compute_apr(principal: float, emi: Decimal, tenure_months: int, total_fees: Decimal) -> Decimal:
    """Compute the Annual Percentage Rate (APR) including fees.

    Uses the Newton-Raphson method to solve for the effective monthly
    rate that equates the loan amount (principal - fees) to the present
    value of all EMI payments.

    Args:
        principal: Loan principal.
        emi: Monthly EMI amount.
        tenure_months: Number of monthly payments.
        total_fees: Total upfront fees deducted from principal.

    Returns:
        APR as a Decimal percentage (e.g. 13.5 for 13.5%).
    """
    net_principal = Decimal(str(principal)) - total_fees
    emi_dec = emi
    n = Decimal(tenure_months)

    if net_principal <= 0 or emi_dec <= 0 or n <= 0:
        return Decimal("0")

    one = Decimal("1")
    rate = Decimal("0.01")
    tolerance = Decimal("0.0001")
    last_diff = None
    for _ in range(200):
        u = (one + rate) ** n
        pv = emi_dec * (u - one) / (rate * u)
        diff = pv - net_principal
        if abs(diff) < tolerance:
            break
        if last_diff is not None and (diff * last_diff) < 0:
            tolerance = tolerance / Decimal("10")
        last_diff = diff
        # dPV/dr = EMI * [ - (1 - 1/u) / r^2 + n / (r * (1+r) * u) ]
        derivative = emi_dec * (-((one - one / u) / (rate * rate)) + (n / (rate * (one + rate) * u)))
        if derivative == 0:
            break
        step = diff / derivative
        if abs(step) > Decimal("0.1"):
            step = Decimal("0.1") if step > 0 else Decimal("-0.1")
        rate -= step
        if rate <= 0:
            rate = Decimal("0.0001")

    return rate * Decimal("1200")


class KfsHandler(Core):
    """Generates Key Fact Statements for loan products.

    Produces a structured KFS document as specified by RBI guidelines,
    including the annual percentage rate (APR), repayment schedule
    summary, fee disclosure, and cooling-off terms.
    """

    def __init__(
        self,
        service_id: str,
        bus: EventBus,
        store: Store,
        identity: Keypair | None = None,
        metrics: Collector | None = None,
        health: Checks | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: Orchestrator | None = None,
        supervisor: Watcher | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize the KFS service with configurable cooling-off period."""
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
        self.__clock: SystemClock = SystemClock()
        self.__cooling_off_days: int = kwargs.get("cooling_off_days", DEFAULT_COOLING_OFF_DAYS)

    def handle(self, event: Message) -> None:
        """Generate a KFS document on request.

        Args:
            event: The incoming domain event.
        """
        if event.event_type == Type.KFS_GENERATE:
            self.__on_kfs_generate(event)

    def __on_kfs_generate(self, event: Message) -> None:
        """Handle a KFS generation request.

        Args:
            event: The KFS generation event.
        """
        p = event.payload
        loan_id: str = p.get("loan_id", "")
        if not loan_id:
            logger.warning("KFS_GENERATE missing loan_id, skipped")
            return

        borrower: str = PayloadValidator().non_empty(p, "borrower", "")
        principal: float = PayloadValidator().finite(p, "principal", 0.0)
        annual_rate: float = PayloadValidator().finite(p, "annual_rate", 0.0)
        tenure_months: int = int(PayloadValidator().finite(p, "tenure_months", 1))
        fees: list[dict[str, Any]] = p.get("fees", [])
        start_date_str: str = p.get("start_date", "")

        sd: date | None = None
        if start_date_str:
            try:
                sd = date.fromisoformat(start_date_str)
            except (ValueError, TypeError):
                sd = None

        try:
            sched = generate_schedule(
                Decimal(str(principal)),
                Decimal(str(annual_rate)),
                tenure_months,
                start_date=sd,
            )
        except Exception as exc:
            logger.error("KFS schedule generation failed for loan {}: {}", loan_id, exc)
            return

        kfs = self.__build_kfs(loan_id, borrower, principal, annual_rate, tenure_months, sched, fees, sd)
        self.emit(
            Type.KFS_GENERATED,
            kfs,
            correlation_id=event.correlation_id,
        )

    def __build_kfs(
        self,
        loan_id: str,
        borrower: str,
        principal: float,
        annual_rate: float,
        tenure_months: int,
        sched: AmortizationSchedule,
        fees: list[dict[str, Any]],
        start_date: date | None = None,
    ) -> dict[str, Any]:
        """Build the KFS document data structure.

        Args:
            loan_id: Unique loan identifier.
            borrower: Borrower identifier.
            principal: Loan principal.
            annual_rate: Annual interest rate in percent.
            tenure_months: Loan tenure in months.
            sched: Amortization schedule.
            fees: List of fee dicts with type and amount.
            start_date: Loan start date.

        Returns:
            KFS document as a dict.
        """
        total_fees = sum(f.get("amount", 0.0) for f in fees)
        apr = compute_apr(principal, sched.emi, tenure_months, Decimal(str(total_fees)))
        generated_at = self.__clock.iso()

        kfs: dict[str, Any] = {
            "loan_id": loan_id,
            "borrower": borrower,
            "generated_at": generated_at,
            "loan_amount": round(principal, 2),
            "annual_interest_rate": annual_rate,
            "annual_percentage_rate": round(float(apr), 2),
            "tenure_months": tenure_months,
            "emi_amount": float(sched.emi),
            "total_interest_payable": float(sched.total_interest),
            "total_repayment": float(sched.total_repayment),
            "fees_and_charges": fees,
            "total_fees": round(total_fees, 2),
            "cooling_off_days": self.__cooling_off_days,
        }
        if start_date:
            kfs["start_date"] = start_date.isoformat()
        return kfs
