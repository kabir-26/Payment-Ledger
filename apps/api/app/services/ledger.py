import uuid
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..errors import DomainError, NotFoundError
from ..models import (
    Account,
    AccountType,
    Currency,
    Direction,
    LedgerEntry,
    LedgerEventType,
    LedgerTransaction,
)


@dataclass(frozen=True)
class EntrySpec:
    account: Account
    direction: Direction
    amount_minor: int
    currency: Currency


def post_transaction(
    session: Session,
    *,
    external_reference: str,
    description: str,
    event_type: LedgerEventType,
    entries: list[EntrySpec],
    invoice_id: UUID | None = None,
) -> LedgerTransaction:
    if len(entries) < 2:
        raise DomainError("A ledger transaction requires at least two entries")

    totals: dict[tuple[Currency, Direction], int] = {}
    for entry in entries:
        if not isinstance(entry.amount_minor, int) or isinstance(entry.amount_minor, bool):
            raise DomainError("Ledger amounts must be integer minor units")
        if entry.amount_minor <= 0:
            raise DomainError("Ledger amounts must be positive")
        if entry.account.currency != entry.currency:
            raise DomainError(
                f"Account {entry.account.code} does not accept {entry.currency.value}"
            )
        key = (entry.currency, entry.direction)
        totals[key] = totals.get(key, 0) + entry.amount_minor

    currencies = {entry.currency for entry in entries}
    for currency in currencies:
        if totals.get((currency, Direction.DEBIT), 0) != totals.get(
            (currency, Direction.CREDIT), 0
        ):
            raise DomainError(f"Debits and credits do not balance for {currency.value}")

    transaction = LedgerTransaction(
        external_reference=external_reference,
        description=description,
        event_type=event_type,
        invoice_id=invoice_id,
    )
    transaction.entries = [
        LedgerEntry(
            account=entry.account,
            direction=entry.direction,
            amount_minor=entry.amount_minor,
            currency=entry.currency,
        )
        for entry in entries
    ]
    session.add(transaction)
    session.flush()
    return transaction


def account_balance(session: Session, account_id: UUID) -> int:
    account = session.get(Account, account_id)
    if not account:
        raise NotFoundError("Account not found")
    debit_positive = account.type in {AccountType.ASSET, AccountType.EXPENSE}
    signed = case(
        (
            LedgerEntry.direction == (Direction.DEBIT if debit_positive else Direction.CREDIT),
            LedgerEntry.amount_minor,
        ),
        else_=-LedgerEntry.amount_minor,
    )
    return int(
        session.scalar(
            select(func.coalesce(func.sum(signed), 0)).where(LedgerEntry.account_id == account.id)
        )
        or 0
    )


def record_transfer(
    session: Session,
    *,
    debit_account_id: UUID,
    credit_account_id: UUID,
    amount_minor: int,
    currency: Currency,
    description: str,
) -> LedgerTransaction:
    description = description.strip()
    if debit_account_id == credit_account_id:
        raise DomainError("Debit and credit accounts must be different")
    if not description or len(description) > 240:
        raise DomainError("Description must be between 1 and 240 characters")
    debit_account = session.get(Account, debit_account_id)
    credit_account = session.get(Account, credit_account_id)
    if not debit_account or not credit_account:
        raise NotFoundError("Debit or credit account not found")
    return post_transaction(
        session,
        external_reference=f"manual:{uuid.uuid4()}",
        description=description,
        event_type=LedgerEventType.MANUAL,
        entries=[
            EntrySpec(debit_account, Direction.DEBIT, amount_minor, currency),
            EntrySpec(credit_account, Direction.CREDIT, amount_minor, currency),
        ],
    )
