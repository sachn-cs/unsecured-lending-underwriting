"""Credit Bureau & CKYC service - pulls credit reports and verifies CKYC.

Integrates with CIBIL, Experian, Equifax for credit bureau checks and
the CKYC registry for identity verification per RBI guidelines.
"""

from __future__ import annotations

from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.metrics import Collector
from underwrite.saga import Orchestrator
from underwrite.services.base import Dependencies, StatefulService
from underwrite.services.credit_bureau.client import (
    CreditBureauClient,
    CreditReport,
    HttpCreditBureauClient,
    MockCreditBureauClient,
)
from underwrite.services.kyc.base import Provider
from underwrite.services.persistence import TypedStoreRepository
from underwrite.store import Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer


class Handler(StatefulService):
    """Pulls credit bureau reports and verifies CKYC identity.

    Delegates HTTP calls to the configured CreditBureauClient. Caches
    reports and CKYC responses in-memory with store persistence.
    """

    def __init__(
        self,
        name: str,
        bus: EventBus,
        store: Store,
        cibil_api_key: str = "",
        allow_mock: bool = False,
        kyc_providers: dict[str, Provider] | None = None,
        identity: Keypair | None = None,
        metrics: Collector | None = None,
        health: Checks | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: Orchestrator | None = None,
        supervisor: Watcher | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
    ) -> None:
        """Initialize the credit bureau service with client and store.

        Args:
            name: Unique name for this service instance.
            bus: Message bus for pub/sub.
            store: State persistence backend.
            cibil_api_key: CIBIL API key (enables HttpCreditBureauClient).
            allow_mock: Permit MockCreditBureauClient when no API key.
            kyc_providers: Optional map of bureau-name -> Provider
                instance. When present the bureau pull routes through
                the configured partner-API client; otherwise the
                legacy HttpCreditBureauClient is used.
            identity: Ed25519 identity for signing events.
            metrics: Optional metrics collector.
            health: Optional health registry.
            authz: Optional access control.
            tracer: Optional distributed tracer.
            saga: Optional saga orchestrator.
            supervisor: Optional service supervisor.
            secrets_manager: Optional secrets manager.
            max_concurrent: Max concurrent handler threads (0=sync).

        """
        deps = Dependencies(
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
        super().__init__(
            name=name,
            bus=deps.bus,
            store=deps.store,
            metrics=deps.metrics,
            health=deps.health,
            authz=deps.authz,
            tracer=deps.tracer,
            saga=deps.saga,
            supervisor=deps.supervisor,
            secrets_manager=deps.secrets_manager,
            max_concurrent=deps.max_concurrent,
        )
        self.__kyc_providers: dict[str, Provider] = dict(kyc_providers or {})
        self.__client: CreditBureauClient = self.build_client(
            cibil_api_key=cibil_api_key,
            allow_mock=allow_mock,
        )
        self.reports: dict[str, CreditReport] = {}
        self.ckyc_records: dict[str, dict[str, Any]] = {}
        self.repo: TypedStoreRepository[dict[str, Any]] = self.store_repo("credit_bureau", dict)
        loaded = self.repo.load(default={})
        if loaded:
            self.reports = {k: Handler.dict_to_report(v) for k, v in loaded.get("reports", {}).items()}
            self.ckyc_records = loaded.get("ckyc", {})

    @property
    def client(self) -> CreditBureauClient:
        """Read-only access to the bureau client for test wiring."""
        return self.__client

    @client.setter
    def client(self, value: CreditBureauClient) -> None:
        self.__client = value

    @staticmethod
    def dict_to_report(d: dict[str, Any]) -> CreditReport:
        """Deserialize a dict to a CreditReport.

        Args:
            d: Dict representation of a CreditReport.

        Returns:
            A CreditReport instance.

        """
        from underwrite.services.credit_bureau.client import (
            BureauAccount,
            BureauEnquiry,
        )

        accounts = [BureauAccount(**a) for a in d.get("accounts", [])]
        enquiries = [BureauEnquiry(**e) for e in d.get("enquiries", [])]
        return CreditReport(
            bureau=d["bureau"],
            pan=d["pan"],
            name=d.get("name", ""),
            dob=d.get("dob", ""),
            score=d.get("score", 0),
            score_factors=d.get("score_factors", []),
            accounts=accounts,
            enquiries=enquiries,
            total_credit_limit=d.get("total_credit_limit", 0.0),
            total_balance=d.get("total_balance", 0.0),
            credit_utilization_pct=d.get("credit_utilization_pct", 0.0),
            active_accounts=d.get("active_accounts", 0),
            delinquent_accounts=d.get("delinquent_accounts", 0),
            credit_age_years=d.get("credit_age_years", 0.0),
            tradelines=d.get("tradelines", 0),
            enquiries_last_30_days=d.get("enquiries_last_30_days", 0),
            defaults=d.get("defaults", []),
            report_date=d.get("report_date", ""),
        )

    def build_client(
        self,
        cibil_api_key: str = "",
        allow_mock: bool = False,
    ) -> CreditBureauClient:
        """Build the appropriate credit bureau client based on config.

        Args:
            cibil_api_key: CIBIL API key.
            allow_mock: Permit MockCreditBureauClient when no API key.

        Returns:
            An HttpCreditBureauClient if credentials are available,
            otherwise a MockCreditBureauClient (only when
            ``allow_mock=True``).

        Raises:
            RuntimeError: If no API key is configured and
                ``allow_mock`` is not explicitly set.
        """
        if cibil_api_key:
            return HttpCreditBureauClient(cibil_api_key=cibil_api_key)
        if allow_mock:
            logger.warning(
                "no bureau credentials configured; using in-memory mock — this must NEVER be set in production"
            )
            return MockCreditBureauClient()
        raise RuntimeError(
            "no credit bureau credentials configured; set cibil_api_key or pass allow_mock=True for tests only"
        )

    def handle(self, event: Message) -> None:
        """Process credit bureau and CKYC verification events.

        Args:
            event: The incoming domain event.

        """
        if event.event_type == Type.CREDIT_BUREAU_CHECK:
            self.check_bureau(event)
        elif event.event_type == Type.CKYC_VERIFY:
            self.verify_ckyc(event)

    def check_bureau(self, event: Message) -> None:
        """Fetch a credit report and emit the result.

        When a ``kyc_providers`` mapping is provided, the bureau
        pull goes through the new CIBIL partner-API client
        (``services.kyc.cibil.CibilBureauClient``). The
        legacy ``HttpCreditBureauClient`` continues to work as a
        fallback for the generic CIBIL/Experian/Equifax endpoints.

        Args:
            event: The CREDIT_BUREAU_CHECK event with pan and
                optional bureau payload.

        """
        pan: str = event.payload.get("pan", "")
        bureau: str = event.payload.get("bureau", "cibil")
        if not pan:
            logger.warning("credit_bureau.check missing pan")
            return
        kyc_providers = self.__kyc_providers
        cibil_provider = kyc_providers.get("cibil") if kyc_providers else None
        if cibil_provider is not None and bureau == "cibil":
            try:
                result = cibil_provider.verify(
                    event.payload.get("consumer_id", pan),
                    name=event.payload.get("name", ""),
                    dob=event.payload.get("dob", ""),
                    pan=pan,
                    address=event.payload.get("address"),
                    consent=event.payload.get("consent", "Y"),
                )
            except Exception as exc:
                logger.error("credit_bureau.check failed for {}: {}", pan, exc)
                self.emit(
                    Type.CREDIT_BUREAU_CHECK_FAILED,
                    {
                        "pan": pan,
                        "bureau": bureau,
                        "error": str(exc),
                    },
                    correlation_id=event.correlation_id,
                )
                return

            if not result.ok:
                self.emit(
                    Type.CREDIT_BUREAU_CHECK_FAILED,
                    {
                        "pan": pan,
                        "bureau": bureau,
                        "verdict": result.verdict.value,
                        "error": result.error,
                    },
                    correlation_id=event.correlation_id,
                )
                return
            details = result.details
            try:
                score = int(details.get("score", 0))
            except (TypeError, ValueError):
                score = 0
            report = CreditReport(
                bureau=bureau,
                pan=pan,
                name=event.payload.get("name", ""),
                dob=event.payload.get("dob", ""),
                score=score,
                tradelines=int(details.get("tradelines", 0)),
                enquiries_last_30_days=int(details.get("enquiries_last_30_days", 0)),
                defaults=list(details.get("defaults", [])),
            )
            with self.state_lock:
                self.reports[pan] = report
                self.sync()
            self.emit(
                Type.CREDIT_BUREAU_CHECKED,
                {
                    "pan": pan,
                    "bureau": bureau,
                    "score": report.score,
                    "score_band": details.get("score_band", ""),
                    "tradelines": report.tradelines,
                    "provider_reference": result.reference,
                },
                correlation_id=event.correlation_id,
            )
            return
        try:
            report = self.__client.fetch_credit_report(pan, bureau)
        except Exception as exc:
            logger.error("credit_bureau.check failed for {}: {}", pan, exc)
            self.emit(
                Type.CREDIT_BUREAU_CHECK_FAILED,
                {
                    "pan": pan,
                    "bureau": bureau,
                    "error": str(exc),
                },
                correlation_id=event.correlation_id,
            )
            return
        with self.state_lock:
            self.reports[pan] = report
            self.sync()
        self.emit(
            Type.CREDIT_BUREAU_CHECKED,
            {
                "pan": pan,
                "bureau": bureau,
                "score": report.score,
                "active_accounts": report.active_accounts,
                "delinquent_accounts": report.delinquent_accounts,
                "credit_utilization_pct": report.credit_utilization_pct,
                "credit_age_years": report.credit_age_years,
                "total_balance": report.total_balance,
            },
            correlation_id=event.correlation_id,
        )

    def verify_ckyc(self, event: Message) -> None:
        """Verify CKYC identity and emit the result.

        Args:
            event: The CKYC_VERIFY event with ckyc_number and aadhaar.

        """
        ckyc_number: str = event.payload.get("ckyc_number", "")
        aadhaar: str = event.payload.get("aadhaar", "")
        if not ckyc_number or not aadhaar:
            logger.warning("ckyc.verify missing ckyc_number or aadhaar")
            return
        try:
            response = self.__client.verify_ckyc(ckyc_number, aadhaar)
        except Exception as exc:
            logger.error("ckyc.verify failed for {}: {}", ckyc_number, exc)
            self.emit(
                Type.CKYC_REJECTED,
                {
                    "ckyc_number": ckyc_number,
                    "error": str(exc),
                },
                correlation_id=event.correlation_id,
            )
            return
        with self.state_lock:
            self.ckyc_records[ckyc_number] = {
                "ckyc_number": response.ckyc_number,
                "name": response.name,
                "dob": response.dob,
                "gender": response.gender,
                "pan": response.pan,
                "aadhaar_verified": response.aadhaar_verified,
                "address": response.address,
                "status": response.status,
                "verified_at": response.verified_at,
            }
            self.sync()
        self.emit(
            Type.CKYC_VERIFIED,
            {
                "ckyc_number": ckyc_number,
                "name": response.name,
                "status": response.status,
            },
            correlation_id=event.correlation_id,
        )

    def get_report(self, pan: str) -> CreditReport | None:
        """Return a cached credit report for a PAN.

        Args:
            pan: The PAN to look up.

        Returns:
            CreditReport or None.

        """
        with self.state_lock:
            return self.reports.get(pan)

    def get_ckyc(self, ckyc_number: str) -> dict[str, Any] | None:
        """Return a cached CKYC record.

        Args:
            ckyc_number: The CKYC number to look up.

        Returns:
            CKYC record dict or None.

        """
        with self.state_lock:
            return self.ckyc_records.get(ckyc_number)

    def health_check(self) -> dict[str, Any]:
        """Bureau-specific health: reports cached report and CKYC counts.

        Returns:
            Health dict extended with reports_cached and ckyc_records
            counts.

        """
        base = super().health_check()
        base["reports_cached"] = len(self.reports)
        base["ckyc_records"] = len(self.ckyc_records)
        return base

    def sync(self) -> None:
        """Persist both reports and CKYC records to the store."""
        reports_dict = {k: Handler.report_to_dict(v) for k, v in self.reports.items()}
        self.repo.save(
            {
                "reports": reports_dict,
                "ckyc": self.ckyc_records,
            }
        )

    @staticmethod
    def report_to_dict(r: CreditReport) -> dict[str, Any]:
        """Serialize a CreditReport to a dict.

        Args:
            r: The CreditReport to serialize.

        Returns:
            Dict representation suitable for store persistence.

        """
        return {
            "bureau": r.bureau,
            "pan": r.pan,
            "name": r.name,
            "dob": r.dob,
            "score": r.score,
            "score_factors": r.score_factors,
            "accounts": [
                {
                    "lender": a.lender,
                    "account_type": a.account_type,
                    "account_number": a.account_number,
                    "opened_date": a.opened_date,
                    "last_reported_date": a.last_reported_date,
                    "current_balance": a.current_balance,
                    "sanction_amount": a.sanction_amount,
                    "emi_amount": a.emi_amount,
                    "days_past_due": a.days_past_due,
                    "status": a.status,
                    "written_off": a.written_off,
                    "settled": a.settled,
                }
                for a in r.accounts
            ],
            "enquiries": [
                {
                    "lender": e.lender,
                    "date": e.date,
                    "amount": e.amount,
                    "purpose": e.purpose,
                }
                for e in r.enquiries
            ],
            "total_credit_limit": r.total_credit_limit,
            "total_balance": r.total_balance,
            "credit_utilization_pct": r.credit_utilization_pct,
            "active_accounts": r.active_accounts,
            "delinquent_accounts": r.delinquent_accounts,
            "credit_age_years": r.credit_age_years,
            "tradelines": r.tradelines,
            "enquiries_last_30_days": r.enquiries_last_30_days,
            "defaults": r.defaults,
            "report_date": r.report_date,
        }
