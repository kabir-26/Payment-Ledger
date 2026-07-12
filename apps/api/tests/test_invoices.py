import pytest
from sqlalchemy import func, select

from app.errors import InvalidTransitionError
from app.models import Direction, InvoiceStatus, LedgerEntry, LedgerTransaction
from app.services.invoices import send_invoice
from tests.helpers import make_invoice, seed_accounts

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]


def test_draft_does_not_post_and_send_posts_once_balanced(session) -> None:
    with session.begin():
        seed_accounts(session)
        invoice = make_invoice(session, 12_345)
    assert invoice.status == InvoiceStatus.DRAFT
    assert session.scalar(select(func.count()).select_from(LedgerTransaction)) == 0
    session.rollback()

    with session.begin():
        send_invoice(session, invoice.id)
    transaction = session.scalar(select(LedgerTransaction))
    assert transaction is not None
    entries = session.scalars(
        select(LedgerEntry).where(LedgerEntry.transaction_id == transaction.id)
    ).all()
    assert len(entries) == 2
    assert sum(e.amount_minor for e in entries if e.direction == Direction.DEBIT) == 12_345
    assert sum(e.amount_minor for e in entries if e.direction == Direction.CREDIT) == 12_345
    session.rollback()

    try:
        with session.begin():
            send_invoice(session, invoice.id)
    except InvalidTransitionError:
        pass
    else:
        raise AssertionError("Sending twice must fail")
    assert session.scalar(select(func.count()).select_from(LedgerTransaction)) == 1
