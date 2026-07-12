import os
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.config import Config

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def session_factory(database_url: str):
    os.environ["DATABASE_URL"] = database_url
    config = Config("apps/api/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url, pool_pre_ping=True)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def clean_database(session_factory) -> Generator[None, None, None]:
    with session_factory().begin() as session:
        session.execute(
            text(
                "TRUNCATE payments, ledger_entries, ledger_transactions, invoice_line_items, "
                "invoices, accounts RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest.fixture
def session(session_factory) -> Generator[Session, None, None]:
    with session_factory() as value:
        yield value
