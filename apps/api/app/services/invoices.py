import secrets
from datetime import date
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from ..errors import (
    ConflictError,
    DomainError,
    IdempotencyConflictError,
    InvalidTransitionError,
    NotFoundError,
    OverpaymentError,
)
from ..models import (
    Account,
    Currency,
    Direction,
    Invoice,
    InvoiceLineItem,
    InvoiceStatus,
    LedgerEventType,
    Payment,
    PaymentStatus,
)
from .ledger import EntrySpec, post_transaction

MAX_LINE_ITEMS = 100


def create_invoice(
    session: Session,
    *,
    vendor_name: str,
    currency: Currency,
    issue_date: date,
    due_date: date,
    line_items: list[dict[str, object]],
) -> Invoice:
    vendor_name = vendor_name.strip()
    if not vendor_name or len(vendor_name) > 160:
        raise DomainError("Vendor name must be between 1 and 160 characters")
    if due_date < issue_date:
        raise DomainError("Due date cannot be before issue date")
    if not line_items or len(line_items) > MAX_LINE_ITEMS:
        raise DomainError(f"An invoice requires 1 to {MAX_LINE_ITEMS} line items")

    normalized: list[InvoiceLineItem] = []
    total = 0
    for item in line_items:
        description = str(item["description"]).strip()
        quantity = item["quantity"]
        unit_amount = item["unit_amount_minor"]
        if not description or len(description) > 240:
            raise DomainError("Line descriptions must be between 1 and 240 characters")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise DomainError("Line quantities must be positive integers")
        if not isinstance(unit_amount, int) or isinstance(unit_amount, bool) or unit_amount <= 0:
            raise DomainError("Unit amounts must be positive integer minor units")
        total += quantity * unit_amount
        if total > 2_147_483_647:
            raise DomainError("Invoice total exceeds the supported limit")
        normalized.append(
            InvoiceLineItem(
                description=description, quantity=quantity, unit_amount_minor=unit_amount
            )
        )

    invoice = Invoice(
        invoice_number=f"INV-{date.today():%Y%m%d}-{secrets.token_hex(3).upper()}",
        vendor_name=vendor_name,
        currency=currency,
        issue_date=issue_date,
        due_date=due_date,
        total_amount_minor=total,
        status=InvoiceStatus.DRAFT,
        line_items=normalized,
    )
    session.add(invoice)
    session.flush()
    return invoice


def _system_accounts(session: Session, currency: Currency) -> dict[str, Account]:
    codes = ["OPERATING_BANK", "ACCOUNTS_PAYABLE", "FREIGHT_EXPENSE"]
    accounts = session.scalars(
        select(Account).where(Account.code.in_(codes), Account.currency == currency)
    ).all()
    result = {account.code: account for account in accounts}
    missing = set(codes) - result.keys()
    if missing:
        raise ConflictError(f"Missing seeded system accounts: {', '.join(sorted(missing))}")
    return result


def send_invoice(session: Session, invoice_id: UUID) -> Invoice:
    invoice = session.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if not invoice:
        raise NotFoundError("Invoice not found")
    if invoice.status != InvoiceStatus.DRAFT:
        raise InvalidTransitionError("Only a draft invoice can be sent")
    accounts = _system_accounts(session, invoice.currency)
    post_transaction(
        session,
        external_reference=f"invoice:{invoice.id}:posted",
        description=f"Post {invoice.invoice_number} from {invoice.vendor_name}",
        event_type=LedgerEventType.INVOICE_POSTED,
        invoice_id=invoice.id,
        entries=[
            EntrySpec(
                accounts["FREIGHT_EXPENSE"],
                Direction.DEBIT,
                invoice.total_amount_minor,
                invoice.currency,
            ),
            EntrySpec(
                accounts["ACCOUNTS_PAYABLE"],
                Direction.CREDIT,
                invoice.total_amount_minor,
                invoice.currency,
            ),
        ],
    )
    invoice.status = InvoiceStatus.SENT
    invoice.version += 1
    session.flush()
    return invoice


def total_paid(session: Session, invoice_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(
                Payment.invoice_id == invoice_id, Payment.status == PaymentStatus.SUCCEEDED
            )
        )
        or 0
    )


def apply_payment(
    session: Session,
    *,
    invoice_id: UUID,
    external_payment_id: str,
    amount_minor: int,
    currency: Currency,
) -> Payment:
    external_payment_id = external_payment_id.strip()
    if not external_payment_id or len(external_payment_id) > 180:
        raise DomainError("External payment ID must be between 1 and 180 characters")
    if not isinstance(amount_minor, int) or isinstance(amount_minor, bool) or amount_minor <= 0:
        raise DomainError("Payment amount must be a positive integer minor-unit value")

    # Serialize global idempotency-key handling before locking the target invoice.
    if session.bind and session.bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": external_payment_id}
        )

    existing = session.scalar(
        select(Payment)
        .options(selectinload(Payment.ledger_transaction))
        .where(Payment.external_payment_id == external_payment_id)
    )
    if existing:
        if (
            existing.invoice_id == invoice_id
            and existing.amount_minor == amount_minor
            and existing.currency == currency
        ):
            return existing
        raise IdempotencyConflictError("External payment ID was already used with different data")

    invoice = session.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if not invoice:
        raise NotFoundError("Invoice not found")
    if invoice.status not in {
        InvoiceStatus.SENT,
        InvoiceStatus.PARTIALLY_PAID,
        InvoiceStatus.OVERDUE,
    }:
        raise InvalidTransitionError("Payments can only be applied to an unpaid posted invoice")
    if invoice.currency != currency:
        raise DomainError("Payment currency must match invoice currency")

    paid = total_paid(session, invoice.id)
    outstanding = invoice.total_amount_minor - paid
    if amount_minor > outstanding:
        raise OverpaymentError(f"Payment exceeds outstanding amount of {outstanding}")

    accounts = _system_accounts(session, invoice.currency)
    ledger_transaction = post_transaction(
        session,
        external_reference=f"payment:{external_payment_id}",
        description=f"Payment {external_payment_id} for {invoice.invoice_number}",
        event_type=LedgerEventType.PAYMENT_APPLIED,
        invoice_id=invoice.id,
        entries=[
            EntrySpec(accounts["ACCOUNTS_PAYABLE"], Direction.DEBIT, amount_minor, currency),
            EntrySpec(accounts["OPERATING_BANK"], Direction.CREDIT, amount_minor, currency),
        ],
    )
    payment = Payment(
        invoice=invoice,
        external_payment_id=external_payment_id,
        amount_minor=amount_minor,
        currency=currency,
        status=PaymentStatus.SUCCEEDED,
        ledger_transaction=ledger_transaction,
    )
    session.add(payment)
    invoice.status = (
        InvoiceStatus.PAID if amount_minor == outstanding else InvoiceStatus.PARTIALLY_PAID
    )
    invoice.version += 1
    session.flush()
    return payment


def effective_status(invoice: Invoice, today: date | None = None) -> InvoiceStatus:
    today = today or date.today()
    if (
        invoice.status in {InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID}
        and invoice.due_date < today
    ):
        return InvoiceStatus.OVERDUE
    return invoice.status
