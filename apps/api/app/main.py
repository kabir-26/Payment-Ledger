from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from strawberry.fastapi import GraphQLRouter

from .config import get_settings
from .db import Base, SessionLocal, engine
from .models import Account, AccountType, Currency
from .schema import schema


async def get_context() -> AsyncGenerator[dict[str, object], None]:
    with SessionLocal() as session:
        yield {"session": session}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # SQLite is the zero-Docker local mode. PostgreSQL uses Alembic migrations.
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
        # Older local databases allowed REVENUE/EQUITY. Both were credit-normal,
        # so LIABILITY preserves their derived-balance sign without deleting data.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE accounts SET type = 'LIABILITY' "
                    "WHERE type IN ('REVENUE', 'EQUITY')"
                )
            )
        with SessionLocal.begin() as session:
            existing = {account.code for account in session.query(Account).all()}
            defaults = (
                ("OPERATING_BANK", "Operating Bank", AccountType.ASSET),
                ("ACCOUNTS_PAYABLE", "Accounts Payable", AccountType.LIABILITY),
                ("FREIGHT_EXPENSE", "Freight Expense", AccountType.EXPENSE),
            )
            for code, name, account_type in defaults:
                if code not in existing:
                    session.add(
                        Account(
                            code=code,
                            name=name,
                            type=account_type,
                            currency=Currency.USD,
                        )
                    )
    yield


app = FastAPI(title="Mini Payment Ledger API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

graphql_app = GraphQLRouter(schema, context_getter=get_context)
app.include_router(graphql_app, prefix="/graphql")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
