from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import Account, AccountType, Currency, Invoice
from app.services.invoices import create_invoice, send_invoice


def seed_accounts(session: Session) -> None:
    session.add_all(
        [
            Account(
                code="OPERATING_BANK",
                name="Operating Bank",
                type=AccountType.ASSET,
                currency=Currency.USD,
            ),
            Account(
                code="ACCOUNTS_PAYABLE",
                name="Accounts Payable",
                type=AccountType.LIABILITY,
                currency=Currency.USD,
            ),
            Account(
                code="FREIGHT_EXPENSE",
                name="Freight Expense",
                type=AccountType.EXPENSE,
                currency=Currency.USD,
            ),
        ]
    )


def make_invoice(session: Session, total_minor: int = 10_00, sent: bool = False) -> Invoice:
    invoice = create_invoice(
        session,
        vendor_name="North Star Freight",
        currency=Currency.USD,
        issue_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        line_items=[{"description": "Linehaul", "quantity": 1, "unit_amount_minor": total_minor}],
    )
    if sent:
        send_invoice(session, invoice.id)
    return invoice
