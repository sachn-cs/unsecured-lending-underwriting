"""Legal notice generation per SARFAESI Act timelines.

Item 35 from production roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass

from ulu.infra.logging import logger


@dataclass
class LegalNotice:
    """Represents a generated legal notice."""

    notice_type: str
    borrower_id: str
    loan_id: str
    days_overdue: int
    principal_outstanding: float
    content: str
    generated_at: str


class LegalNoticeService:
    """Generates 60-day, 90-day, and 120-day legal notices."""

    NOTICE_TEMPLATES: dict[str, str] = {
        "60_day": (
            "NOTICE OF DEFAULT\n\n"
            "To: {borrower_id}\n"
            "Loan ID: {loan_id}\n"
            "Days Overdue: {days_overdue}\n"
            "Principal Outstanding: INR {principal_outstanding:,.2f}\n\n"
            "You are hereby notified that your loan account is overdue. "
            "Please remit the outstanding amount within 30 days to avoid further action.\n\n"
            "This notice is issued under Section 13(2) of the SARFAESI Act, 2002."
        ),
        "90_day": (
            "DEMAND NOTICE\n\n"
            "To: {borrower_id}\n"
            "Loan ID: {loan_id}\n"
            "Days Overdue: {days_overdue}\n"
            "Principal Outstanding: INR {principal_outstanding:,.2f}\n\n"
            "Despite earlier notice dated {earlier_notice_date}, the outstanding amount remains unpaid. "
            "You are required to pay the full amount within 15 days, failing which "
            "the secured asset may be taken possession of under Section 13(4) of the SARFAESI Act, 2002."
        ),
        "120_day": (
            "POSSESSION NOTICE\n\n"
            "To: {borrower_id}\n"
            "Loan ID: {loan_id}\n"
            "Days Overdue: {days_overdue}\n"
            "Principal Outstanding: INR {principal_outstanding:,.2f}\n\n"
            "You have failed to repay the outstanding amount despite repeated notices. "
            "We hereby invoke the provisions of Section 13(4) of the SARFAESI Act, 2002, "
            "and take symbolic possession of the secured assets. "
            "You may file an appeal with the Debt Recovery Tribunal within 45 days."
        ),
    }

    def generate_notice(
        self,
        borrower_id: str,
        loan_id: str,
        days_overdue: int,
        principal_outstanding: float,
        notice_type: str,
        generated_at: str = "",
        earlier_notice_date: str = "",
    ) -> LegalNotice:
        """Generates a legal notice based on type and parameters."""
        template = self.NOTICE_TEMPLATES.get(notice_type)
        if template is None:
            raise ValueError(f"unknown notice type: {notice_type}")

        content = template.format(
            borrower_id=borrower_id,
            loan_id=loan_id,
            days_overdue=days_overdue,
            principal_outstanding=principal_outstanding,
            earlier_notice_date=earlier_notice_date,
        )
        notice = LegalNotice(
            notice_type=notice_type,
            borrower_id=borrower_id,
            loan_id=loan_id,
            days_overdue=days_overdue,
            principal_outstanding=principal_outstanding,
            content=content,
            generated_at=generated_at,
        )
        logger.info(
            "legal_notice_generated",
            notice_type=notice_type,
            borrower_id=borrower_id,
            loan_id=loan_id,
        )
        return notice

    def get_notice_type(self, days_overdue: int) -> str:
        """Returns appropriate notice type based on days overdue."""
        if days_overdue >= 120:
            return "120_day"
        if days_overdue >= 90:
            return "90_day"
        if days_overdue >= 60:
            return "60_day"
        return "reminder"
