import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.models import Account, AccountType, Currency  # noqa: E402

SYSTEM_ACCOUNTS = (
    ("OPERATING_BANK", "Operating Bank", AccountType.ASSET),
    ("ACCOUNTS_PAYABLE", "Accounts Payable", AccountType.LIABILITY),
    ("FREIGHT_EXPENSE", "Freight & Transportation Expense", AccountType.EXPENSE),
)


def seed() -> None:
    with SessionLocal.begin() as session:
        existing = set(session.scalars(select(Account.code)).all())
        for code, name, account_type in SYSTEM_ACCOUNTS:
            if code not in existing:
                session.add(Account(code=code, name=name, type=account_type, currency=Currency.USD))
    print("Seeded system accounts (safe to run repeatedly).")


if __name__ == "__main__":
    seed()
