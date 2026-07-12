from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app.errors import IdempotencyConflictError, OverpaymentError
from app.models import (
    Currency,
    Direction,
    Invoice,
    InvoiceStatus,
    LedgerEntry,
    LedgerTransaction,
    Payment,
)
from app.services.invoices import apply_payment
from tests.helpers import make_invoice, seed_accounts

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]


def _setup_sent_invoice(session, total: int = 1_000):
    with session.begin():
        seed_accounts(session)
        invoice = make_invoice(session, total, sent=True)
    return invoice


def test_partial_final_idempotency_and_overpayment_are_atomic(session) -> None:
    invoice = _setup_sent_invoice(session)
    with session.begin():
        first = apply_payment(
            session,
            invoice_id=invoice.id,
            external_payment_id="pay-001",
            amount_minor=400,
            currency=Currency.USD,
        )
    assert invoice.status == InvoiceStatus.PARTIALLY_PAID
    assert first.amount_minor == 400

    with session.begin():
        replay = apply_payment(
            session,
            invoice_id=invoice.id,
            external_payment_id="pay-001",
            amount_minor=400,
            currency=Currency.USD,
        )
    assert replay.id == first.id
    assert session.scalar(select(func.count()).select_from(Payment)) == 1
    assert session.scalar(select(func.count()).select_from(LedgerTransaction)) == 2
    session.rollback()

    with pytest.raises(IdempotencyConflictError):
        with session.begin():
            apply_payment(
                session,
                invoice_id=invoice.id,
                external_payment_id="pay-001",
                amount_minor=399,
                currency=Currency.USD,
            )

    with pytest.raises(OverpaymentError):
        with session.begin():
            apply_payment(
                session,
                invoice_id=invoice.id,
                external_payment_id="pay-too-large",
                amount_minor=601,
                currency=Currency.USD,
            )
    assert session.scalar(select(func.count()).select_from(Payment)) == 1
    session.rollback()

    with session.begin():
        apply_payment(
            session,
            invoice_id=invoice.id,
            external_payment_id="pay-002",
            amount_minor=600,
            currency=Currency.USD,
        )
    assert invoice.status == InvoiceStatus.PAID
    assert sum(payment.amount_minor for payment in invoice.payments) == 1_000


def test_concurrent_payments_cannot_overpay_and_all_postings_balance(
    session_factory, session
) -> None:
    invoice = _setup_sent_invoice(session)
    invoice_id = invoice.id
    session.close()

    def attempt(external_id: str) -> str:
        with session_factory() as worker:
            try:
                with worker.begin():
                    apply_payment(
                        worker,
                        invoice_id=invoice_id,
                        external_payment_id=external_id,
                        amount_minor=600,
                        currency=Currency.USD,
                    )
                return "accepted"
            except OverpaymentError:
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ["concurrent-a", "concurrent-b"]))

    assert sorted(results) == ["accepted", "rejected"]
    with session_factory() as verification:
        paid = verification.scalar(select(func.coalesce(func.sum(Payment.amount_minor), 0)))
        assert paid == 600
        refreshed = verification.get(Invoice, invoice_id)
        assert refreshed is not None and refreshed.status == InvoiceStatus.PARTIALLY_PAID
        transactions = verification.scalars(select(LedgerTransaction)).all()
        for transaction in transactions:
            entries = verification.scalars(
                select(LedgerEntry).where(LedgerEntry.transaction_id == transaction.id)
            ).all()
            debits = sum(e.amount_minor for e in entries if e.direction == Direction.DEBIT)
            credits = sum(e.amount_minor for e in entries if e.direction == Direction.CREDIT)
            assert len(entries) >= 2
            assert debits == credits
