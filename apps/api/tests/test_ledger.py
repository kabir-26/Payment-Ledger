import uuid

import pytest
from sqlalchemy import func, select

from app.errors import DomainError
from app.models import Account, Currency, Direction, LedgerEntry, LedgerEventType
from app.services.ledger import EntrySpec, account_balance, post_transaction
from tests.helpers import seed_accounts

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]


def test_balanced_transaction_and_derived_balances_are_exact(session) -> None:
    with session.begin():
        seed_accounts(session)
        session.flush()
        accounts = {account.code: account for account in session.scalars(select(Account)).all()}
        transaction = post_transaction(
            session,
            external_reference="manual:exact-cents",
            description="Exact cents check",
            event_type=LedgerEventType.MANUAL,
            entries=[
                EntrySpec(accounts["FREIGHT_EXPENSE"], Direction.DEBIT, 10_01, Currency.USD),
                EntrySpec(accounts["ACCOUNTS_PAYABLE"], Direction.CREDIT, 10_01, Currency.USD),
            ],
        )

    debits = sum(
        entry.amount_minor for entry in transaction.entries if entry.direction == Direction.DEBIT
    )
    credits = sum(
        entry.amount_minor for entry in transaction.entries if entry.direction == Direction.CREDIT
    )
    assert debits == credits == 10_01
    assert account_balance(session, accounts["FREIGHT_EXPENSE"].id) == 10_01
    assert account_balance(session, accounts["ACCOUNTS_PAYABLE"].id) == 10_01


def test_unbalanced_transaction_is_rejected_without_writes(session) -> None:
    with session.begin():
        seed_accounts(session)
    accounts = {account.code: account for account in session.scalars(select(Account)).all()}
    session.rollback()

    with pytest.raises(DomainError, match="do not balance"):
        with session.begin():
            post_transaction(
                session,
                external_reference=f"manual:{uuid.uuid4()}",
                description="Must fail",
                event_type=LedgerEventType.MANUAL,
                entries=[
                    EntrySpec(accounts["FREIGHT_EXPENSE"], Direction.DEBIT, 101, Currency.USD),
                    EntrySpec(accounts["ACCOUNTS_PAYABLE"], Direction.CREDIT, 100, Currency.USD),
                ],
            )
    assert session.scalar(select(func.count()).select_from(LedgerEntry)) == 0


def test_posted_entries_cannot_be_mutated(session) -> None:
    with session.begin():
        seed_accounts(session)
        session.flush()
        accounts = {account.code: account for account in session.scalars(select(Account)).all()}
        transaction = post_transaction(
            session,
            external_reference="manual:immutable",
            description="Immutable",
            event_type=LedgerEventType.MANUAL,
            entries=[
                EntrySpec(accounts["FREIGHT_EXPENSE"], Direction.DEBIT, 500, Currency.USD),
                EntrySpec(accounts["ACCOUNTS_PAYABLE"], Direction.CREDIT, 500, Currency.USD),
            ],
        )
    transaction.entries[0].amount_minor = 400
    with pytest.raises(ValueError, match="immutable"):
        session.commit()
    session.rollback()
