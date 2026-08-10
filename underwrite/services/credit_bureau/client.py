"""Credit bureau HTTP client abstraction with mock support.

Supports CIBIL, Experian, Equifax credit reports and CKYC verification.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from underwrite.metrics import SystemClock

try:
    import httpx

    HAS_HTTPX = True
except ImportError:  # pragma: no cover
    HAS_HTTPX = False


class CreditBureauError(Exception):
    """Raised when a bureau API returns an error."""


class CreditBureauAuthError(CreditBureauError):
    """Raised on authentication/authorization failures."""


class CreditBureauNotFoundError(CreditBureauError):
    """Raised when a record is not found."""


class CreditBureauValidationError(CreditBureauError):
    """Raised on request validation errors."""


@dataclass(frozen=True, slots=True)
class BureauAccount:
    """A credit account reported by the bureau."""

    lender: str
    account_type: str
    account_number: str
    opened_date: str
    last_reported_date: str
    current_balance: float
    sanction_amount: float
    emi_amount: float
    days_past_due: int
    status: str
    written_off: bool = False
    settled: bool = False


@dataclass(frozen=True, slots=True)
class BureauEnquiry:
    """A credit enquiry from a lender."""

    lender: str
    date: str
    amount: float
    purpose: str


@dataclass(slots=True)
class CreditReport:
    """Consolidated credit bureau report (bureau-agnostic)."""

    bureau: str
    pan: str
    name: str
    dob: str
    score: int
    score_range: tuple[int, int] = (300, 900)
    score_factors: list[str] = field(default_factory=list)
    accounts: list[BureauAccount] = field(default_factory=list)
    enquiries: list[BureauEnquiry] = field(default_factory=list)
    total_credit_limit: float = 0.0
    total_balance: float = 0.0
    credit_utilization_pct: float = 0.0
    active_accounts: int = 0
    delinquent_accounts: int = 0
    credit_age_years: float = 0.0
    tradelines: int = 0
    enquiries_last_30_days: int = 0
    defaults: list[str] = field(default_factory=list)
    report_date: str = field(default_factory=lambda: SystemClock().iso())


@dataclass(frozen=True, slots=True)
class CkycResponse:
    """CKYC verification response."""

    ckyc_number: str
    name: str
    dob: str
    gender: str
    pan: str
    aadhaar_verified: bool
    address: str
    status: str
    verified_at: str = field(default_factory=lambda: SystemClock().iso())


class CreditBureauClient(ABC):
    """Abstract credit bureau client.

    Implementations provide fetch_credit_report and verify_ckyc.
    """

    @abstractmethod
    def fetch_credit_report(
        self,
        pan: str,
        bureau: str = "cibil",
    ) -> CreditReport:
        """Fetch a credit report from the given bureau.

        Args:
            pan: Permanent Account Number (10 chars).
            bureau: Bureau name (cibil, experian, equifax).

        Returns:
            A CreditReport with parsed data.
        """

    @abstractmethod
    def verify_ckyc(
        self,
        ckyc_number: str,
        aadhaar: str,
    ) -> CkycResponse:
        """Verify a customer via the CKYC registry.

        Args:
            ckyc_number: 14-digit CKYC number.
            aadhaar: Aadhaar number (last 4 digits for consent).

        Returns:
            A CkycResponse with verification status.
        """


class HttpCreditBureauClient(CreditBureauClient):
    """Production bureau client using httpx.

    Uses configurable base URLs and API keys for each bureau.
    """

    def __init__(
        self,
        cibil_api_key: str = "",
        cibil_api_base: str = "https://api.cibil.com/v1",
        experian_api_key: str = "",
        experian_api_base: str = "https://api.experian.in/v1",
        equifax_api_key: str = "",
        equifax_api_base: str = "https://api.equifax.com/in/v1",
        ckyc_api_key: str = "",
        ckyc_api_base: str = "https://api.ckycindia.in/v1",
        timeout_seconds: int = 30,
        clock: SystemClock | None = None,
    ) -> None:
        """Initialize the HTTP bureau client.

        Args:
            cibil_api_key: API key for CIBIL.
            cibil_api_base: Base URL for CIBIL API.
            experian_api_key: API key for Experian.
            experian_api_base: Base URL for Experian API.
            equifax_api_key: API key for Equifax.
            equifax_api_base: Base URL for Equifax API.
            ckyc_api_key: API key for CKYC registry.
            ckyc_api_base: Base URL for CKYC API.
            timeout_seconds: HTTP request timeout.
            clock: Optional time source; defaults to SystemClock(). Used
                to stamp report_date and verified_at when the upstream
                response omits them.
        """
        self.__cibil_api_key = cibil_api_key
        self.__cibil_api_base = cibil_api_base.rstrip("/")
        self.__experian_api_key = experian_api_key
        self.__experian_api_base = experian_api_base.rstrip("/")
        self.__equifax_api_key = equifax_api_key
        self.__equifax_api_base = equifax_api_base.rstrip("/")
        self.__ckyc_api_key = ckyc_api_key
        self.__ckyc_api_base = ckyc_api_base.rstrip("/")
        self.__timeout = timeout_seconds
        self.__clock = clock if clock is not None else SystemClock()
        self.__http = httpx.Client(timeout=self.__timeout)

    def request(
        self,
        method: str,
        base_url: str,
        path: str,
        api_key: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request and return the JSON response body.

        Args:
            method: HTTP method.
            base_url: Base URL for the API.
            path: API path.
            api_key: Bearer token for authorization.
            data: Optional JSON request body.

        Returns:
            Parsed JSON response dict.

        Raises:
            CreditBureauError: On request or response errors.
        """
        from urllib.parse import urljoin

        url = urljoin(base_url + "/", path.lstrip("/"))
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            if not HAS_HTTPX:
                raise RuntimeError("httpx is required for HttpCreditBureauClient")
            resp = self.__http.request(method, url, json=data, headers=headers)
        except httpx.TimeoutException as exc:
            raise CreditBureauError(f"request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise CreditBureauError(f"request failed: {exc}") from exc
        return self.handle_response(resp)

    def handle_response(self, resp: httpx.Response) -> dict[str, Any]:
        """Parse and validate an HTTP response.

        Args:
            resp: The httpx Response object.

        Returns:
            Parsed JSON body.

        Raises:
            CreditBureauAuthError: On 401.
            CreditBureauNotFoundError: On 404.
            CreditBureauValidationError: On 400.
            CreditBureauError: On other errors.
        """
        import json as json_mod

        try:
            body = resp.json()
        except (json_mod.JSONDecodeError, httpx.DecodingError) as exc:
            raise CreditBureauError(f"invalid JSON response ({resp.status_code}): {exc}") from exc
        if resp.status_code == 401:
            raise CreditBureauAuthError(body.get("error", {}).get("message", "unauthorized"))
        if resp.status_code == 404:
            raise CreditBureauNotFoundError(body.get("error", {}).get("message", "not found"))
        if resp.status_code == 400:
            raise CreditBureauValidationError(body.get("error", {}).get("message", "validation error"))
        if not resp.is_success:
            raise CreditBureauError(
                f"API error ({resp.status_code}): {body.get('error', {}).get('message', 'unknown')}"
            )
        return body

    def get_base(self, bureau: str) -> tuple[str, str]:
        """Return the base URL and API key for a given bureau.

        Args:
            bureau: Bureau name (cibil, experian, equifax).

        Returns:
            Tuple of (base_url, api_key).

        Raises:
            CreditBureauValidationError: If bureau is unsupported.
        """
        bases = {
            "cibil": (self.__cibil_api_base, self.__cibil_api_key),
            "experian": (self.__experian_api_base, self.__experian_api_key),
            "equifax": (self.__equifax_api_base, self.__equifax_api_key),
        }
        entry = bases.get(bureau)
        if not entry:
            raise CreditBureauValidationError(f"unsupported bureau: {bureau}")
        return entry

    def fetch_credit_report(
        self,
        pan: str,
        bureau: str = "cibil",
    ) -> CreditReport:
        """Fetch a credit report from the specified bureau.

        Args:
            pan: The PAN to look up.
            bureau: Bureau to query (cibil, experian, equifax).

        Returns:
            Parsed CreditReport.

        Raises:
            CreditBureauError: On API errors.
        """
        base_url, api_key = self.get_base(bureau)
        body = self.request("POST", base_url, "/credit-report", api_key, {"pan": pan})
        accounts = [
            BureauAccount(
                lender=acc.get("lender", ""),
                account_type=acc.get("account_type", ""),
                account_number=acc.get("account_number", ""),
                opened_date=acc.get("opened_date", ""),
                last_reported_date=acc.get("last_reported_date", ""),
                current_balance=float(acc.get("current_balance", 0)),
                sanction_amount=float(acc.get("sanction_amount", 0)),
                emi_amount=float(acc.get("emi_amount", 0)),
                days_past_due=acc.get("days_past_due", 0),
                status=acc.get("status", ""),
                written_off=acc.get("written_off", False),
                settled=acc.get("settled", False),
            )
            for acc in body.get("accounts", [])
        ]
        enquiries = [
            BureauEnquiry(
                lender=enq.get("lender", ""),
                date=enq.get("date", ""),
                amount=float(enq.get("amount", 0)),
                purpose=enq.get("purpose", ""),
            )
            for enq in body.get("enquiries", [])
        ]
        return CreditReport(
            bureau=bureau,
            pan=pan,
            name=body.get("name", ""),
            dob=body.get("dob", ""),
            score=body.get("score", 0),
            score_factors=body.get("score_factors", []),
            accounts=accounts,
            enquiries=enquiries,
            total_credit_limit=float(body.get("total_credit_limit", 0)),
            total_balance=float(body.get("total_balance", 0)),
            credit_utilization_pct=float(body.get("credit_utilization_pct", 0)),
            active_accounts=body.get("active_accounts", 0),
            delinquent_accounts=body.get("delinquent_accounts", 0),
            credit_age_years=float(body.get("credit_age_years", 0)),
            tradelines=body.get("tradelines", 0),
            enquiries_last_30_days=body.get("enquiries_last_30_days", 0),
            defaults=body.get("defaults", []),
            report_date=body.get("report_date", "") or self.__clock.iso(),
        )

    def verify_ckyc(
        self,
        ckyc_number: str,
        aadhaar: str,
    ) -> CkycResponse:
        """Verify a customer via the CKYC registry.

        Args:
            ckyc_number: 14-digit CKYC number.
            aadhaar: Aadhaar number.

        Returns:
            CkycResponse with verification status.
        """
        body = self.request(
            "POST",
            self.__ckyc_api_base,
            "/verify",
            self.__ckyc_api_key,
            {"ckyc_number": ckyc_number, "aadhaar": aadhaar},
        )
        return CkycResponse(
            ckyc_number=body.get("ckyc_number", ckyc_number),
            name=body.get("name", ""),
            dob=body.get("dob", ""),
            gender=body.get("gender", ""),
            pan=body.get("pan", ""),
            aadhaar_verified=body.get("aadhaar_verified", False),
            address=body.get("address", ""),
            status=body.get("status", "verified"),
            verified_at=body.get("verified_at", "") or self.__clock.iso(),
        )


class MockCreditBureauClient(CreditBureauClient):
    """In-memory mock bureau client for testing.

    Stores pre-configured credit reports and CKYC responses. Supports
    configurable failure modes via fail_on.
    """

    def __init__(self) -> None:
        self.reports: dict[str, CreditReport] = {}
        self.ckyc_responses: dict[str, CkycResponse] = {}
        self.fail_on: dict[str, Exception] = {}

    def check_fail(self, action: str) -> None:
        """Raise a pre-configured exception for the given action, if any.

        Args:
            action: The action name to check.
        """
        exc = self.fail_on.get(action)
        if exc is not None:
            raise exc

    def add_report(self, pan: str, report: CreditReport) -> None:
        """Pre-populate a credit report for testing.

        Args:
            pan: The PAN to associate with the report.
            report: The CreditReport to store.
        """
        self.reports[pan] = report

    def add_ckyc(self, ckyc_number: str, response: CkycResponse) -> None:
        """Pre-populate a CKYC response for testing.

        Args:
            ckyc_number: The CKYC number to associate.
            response: The CkycResponse to store.
        """
        self.ckyc_responses[ckyc_number] = response

    def fetch_credit_report(
        self,
        pan: str,
        bureau: str = "cibil",
    ) -> CreditReport:
        self.check_fail("fetch_credit_report")
        report = self.reports.get(pan)
        if report is None:
            raise CreditBureauNotFoundError(f"no credit report found for PAN {pan}")
        return report

    def verify_ckyc(
        self,
        ckyc_number: str,
        aadhaar: str,
    ) -> CkycResponse:
        self.check_fail("verify_ckyc")
        resp = self.ckyc_responses.get(ckyc_number)
        if resp is None:
            raise CreditBureauNotFoundError(f"no CKYC record found for {ckyc_number}")
        return resp
