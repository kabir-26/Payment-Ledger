import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import Base
from app.errors import DomainError, IdempotencyConflictError, OverpaymentError
from app.models import (
    Account,
    Currency,
    Direction,
    InvoiceStatus,
    LedgerEntry,
    LedgerEventType,
    LedgerTransaction,
    Payment,
)
from app.services.invoices import apply_payment
from app.services.ledger import EntrySpec, account_balance, post_transaction, record_transfer
from tests.helpers import make_invoice, seed_accounts


@pytest.fixture
def unit_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def test_exact_balanced_entries_and_derived_balance(unit_session) -> None:
    with unit_session.begin():
        seed_accounts(unit_session)
        unit_session.flush()
        accounts = {item.code: item for item in unit_session.scalars(select(Account)).all()}
        post_transaction(
            unit_session,
            external_reference="unit:exact",
            description="Exact minor units",
            event_type=LedgerEventType.MANUAL,
            entries=[
                EntrySpec(accounts["FREIGHT_EXPENSE"], Direction.DEBIT, 1_001, Currency.USD),
                EntrySpec(accounts["ACCOUNTS_PAYABLE"], Direction.CREDIT, 1_001, Currency.USD),
            ],
        )
    assert account_balance(unit_session, accounts["FREIGHT_EXPENSE"].id) == 1_001
    assert account_balance(unit_session, accounts["ACCOUNTS_PAYABLE"].id) == 1_001


def test_unbalanced_posting_is_rejected_before_persistence(unit_session) -> None:
    with unit_session.begin():
        seed_accounts(unit_session)
    accounts = {item.code: item for item in unit_session.scalars(select(Account)).all()}
    unit_session.rollback()
    with pytest.raises(DomainError, match="do not balance"):
        with unit_session.begin():
            post_transaction(
                unit_session,
                external_reference=f"unit:{uuid.uuid4()}",
                description="Unbalanced",
                event_type=LedgerEventType.MANUAL,
                entries=[
                    EntrySpec(accounts["FREIGHT_EXPENSE"], Direction.DEBIT, 101, Currency.USD),
                    EntrySpec(accounts["ACCOUNTS_PAYABLE"], Direction.CREDIT, 100, Currency.USD),
                ],
            )
    assert unit_session.scalar(select(func.count()).select_from(LedgerEntry)) == 0


def test_manual_transaction_debits_and_credits_two_accounts(unit_session) -> None:
    with unit_session.begin():
        seed_accounts(unit_session)
        unit_session.flush()
        accounts = {item.code: item for item in unit_session.scalars(select(Account)).all()}
        transaction = record_transfer(
            unit_session,
            debit_account_id=accounts["FREIGHT_EXPENSE"].id,
            credit_account_id=accounts["OPERATING_BANK"].id,
            amount_minor=2_501,
            currency=Currency.USD,
            description="Fuel charge",
        )
    assert len(transaction.entries) == 2
    assert {entry.direction for entry in transaction.entries} == {
        Direction.DEBIT,
        Direction.CREDIT,
    }
    assert account_balance(unit_session, accounts["FREIGHT_EXPENSE"].id) == 2_501
    assert account_balance(unit_session, accounts["OPERATING_BANK"].id) == -2_501


def test_invoice_payment_lifecycle_is_atomic_and_idempotent(unit_session) -> None:
    with unit_session.begin():
        seed_accounts(unit_session)
        invoice = make_invoice(unit_session, 1_000)
    assert invoice.status == InvoiceStatus.DRAFT
    assert unit_session.scalar(select(func.count()).select_from(LedgerTransaction)) == 0
    unit_session.rollback()

    with unit_session.begin():
        from app.services.invoices import send_invoice

        send_invoice(unit_session, invoice.id)
    assert invoice.status == InvoiceStatus.SENT

    with unit_session.begin():
        first = apply_payment(
            unit_session,
            invoice_id=invoice.id,
            external_payment_id="unit-pay-1",
            amount_minor=400,
            currency=Currency.USD,
        )
    assert invoice.status == InvoiceStatus.PARTIALLY_PAID

    with unit_session.begin():
        replay = apply_payment(
            unit_session,
            invoice_id=invoice.id,
            external_payment_id="unit-pay-1",
            amount_minor=400,
            currency=Currency.USD,
        )
    assert replay.id == first.id

    with pytest.raises(IdempotencyConflictError):
        with unit_session.begin():
            apply_payment(
                unit_session,
                invoice_id=invoice.id,
                external_payment_id="unit-pay-1",
                amount_minor=401,
                currency=Currency.USD,
            )
    with pytest.raises(OverpaymentError):
        with unit_session.begin():
            apply_payment(
                unit_session,
                invoice_id=invoice.id,
                external_payment_id="unit-overpay",
                amount_minor=601,
                currency=Currency.USD,
            )

    assert unit_session.scalar(select(func.count()).select_from(Payment)) == 1
    unit_session.rollback()
    with unit_session.begin():
        apply_payment(
            unit_session,
            invoice_id=invoice.id,
            external_payment_id="unit-pay-2",
            amount_minor=600,
            currency=Currency.USD,
        )
    assert invoice.status == InvoiceStatus.PAID
    assert sum(payment.amount_minor for payment in invoice.payments) == 1_000
