from datetime import date, datetime
from uuid import UUID

import strawberry
from graphql import GraphQLError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from strawberry.types import Info

from .errors import ConflictError, DomainError, NotFoundError
from .models import (
    Account,
    AccountType,
    Currency,
    Direction,
    Invoice,
    InvoiceStatus,
    LedgerEntry,
    LedgerEventType,
    LedgerTransaction,
    Payment,
    PaymentStatus,
)
from .services.invoices import (
    apply_payment,
    create_invoice,
    effective_status,
    send_invoice,
)
from .services.ledger import account_balance, record_transfer

for graphql_enum in (
    AccountType,
    Currency,
    Direction,
    InvoiceStatus,
    PaymentStatus,
    LedgerEventType,
):
    strawberry.enum(graphql_enum)


def _session(info: Info) -> Session:
    return info.context["session"]


def _graphql_error(error: DomainError) -> GraphQLError:
    return GraphQLError(error.message, extensions={"code": error.code})


@strawberry.type
class AccountRef:
    id: UUID
    code: str
    name: str


@strawberry.type
class LedgerEntryType:
    id: UUID
    account: AccountRef
    direction: Direction
    amount_minor: int
    currency: Currency
    created_at: datetime

    @classmethod
    def from_model(cls, entry: LedgerEntry) -> "LedgerEntryType":
        return cls(
            id=entry.id,
            account=AccountRef(
                id=entry.account.id, code=entry.account.code, name=entry.account.name
            ),
            direction=entry.direction,
            amount_minor=entry.amount_minor,
            currency=entry.currency,
            created_at=entry.created_at,
        )


@strawberry.type
class LedgerTransactionType:
    id: UUID
    external_reference: str
    description: str
    event_type: LedgerEventType
    invoice_id: UUID | None
    created_at: datetime
    entries: list[LedgerEntryType]

    @classmethod
    def from_model(cls, transaction: LedgerTransaction) -> "LedgerTransactionType":
        return cls(
            id=transaction.id,
            external_reference=transaction.external_reference,
            description=transaction.description,
            event_type=transaction.event_type,
            invoice_id=transaction.invoice_id,
            created_at=transaction.created_at,
            entries=[LedgerEntryType.from_model(entry) for entry in transaction.entries],
        )


@strawberry.type
class AccountTypeOutput:
    id: UUID
    code: str
    name: str
    type: AccountType
    currency: Currency
    created_at: datetime
    balance_minor: int
    entries: list[LedgerEntryType]

    @classmethod
    def from_model(cls, account: Account, session: Session) -> "AccountTypeOutput":
        return cls(
            id=account.id,
            code=account.code,
            name=account.name,
            type=account.type,
            currency=account.currency,
            created_at=account.created_at,
            balance_minor=account_balance(session, account.id),
            entries=[LedgerEntryType.from_model(entry) for entry in account.entries],
        )


@strawberry.type
class InvoiceLineItemType:
    id: UUID
    description: str
    quantity: int
    unit_amount_minor: int
    line_total_minor: int


@strawberry.type
class PaymentType:
    id: UUID
    external_payment_id: str
    amount_minor: int
    currency: Currency
    status: PaymentStatus
    created_at: datetime
    ledger_transaction_id: UUID

    @classmethod
    def from_model(cls, payment: Payment) -> "PaymentType":
        return cls(
            id=payment.id,
            external_payment_id=payment.external_payment_id,
            amount_minor=payment.amount_minor,
            currency=payment.currency,
            status=payment.status,
            created_at=payment.created_at,
            ledger_transaction_id=payment.ledger_transaction_id,
        )


@strawberry.type
class InvoiceType:
    id: UUID
    invoice_number: str
    vendor_name: str
    currency: Currency
    issue_date: date
    due_date: date
    status: InvoiceStatus
    total_amount_minor: int
    total_paid_minor: int
    outstanding_amount_minor: int
    version: int
    created_at: datetime
    updated_at: datetime
    line_items: list[InvoiceLineItemType]
    payments: list[PaymentType]
    ledger_transactions: list[LedgerTransactionType]

    @classmethod
    def from_model(cls, invoice: Invoice) -> "InvoiceType":
        paid = sum(
            payment.amount_minor
            for payment in invoice.payments
            if payment.status == PaymentStatus.SUCCEEDED
        )
        return cls(
            id=invoice.id,
            invoice_number=invoice.invoice_number,
            vendor_name=invoice.vendor_name,
            currency=invoice.currency,
            issue_date=invoice.issue_date,
            due_date=invoice.due_date,
            status=effective_status(invoice),
            total_amount_minor=invoice.total_amount_minor,
            total_paid_minor=paid,
            outstanding_amount_minor=invoice.total_amount_minor - paid,
            version=invoice.version,
            created_at=invoice.created_at,
            updated_at=invoice.updated_at,
            line_items=[
                InvoiceLineItemType(
                    id=item.id,
                    description=item.description,
                    quantity=item.quantity,
                    unit_amount_minor=item.unit_amount_minor,
                    line_total_minor=item.line_total_minor,
                )
                for item in invoice.line_items
            ],
            payments=[PaymentType.from_model(payment) for payment in invoice.payments],
            ledger_transactions=[
                LedgerTransactionType.from_model(transaction)
                for transaction in invoice.ledger_transactions
            ],
        )


def _invoice_options():
    return (
        selectinload(Invoice.line_items),
        selectinload(Invoice.payments),
        selectinload(Invoice.ledger_transactions)
        .selectinload(LedgerTransaction.entries)
        .selectinload(LedgerEntry.account),
    )


@strawberry.input
class CreateAccountInput:
    code: str
    name: str
    type: AccountType
    currency: Currency = Currency.USD


@strawberry.input
class InvoiceLineItemInput:
    description: str
    quantity: int
    unit_amount_minor: int


@strawberry.input
class CreateInvoiceInput:
    vendor_name: str
    currency: Currency
    issue_date: date
    due_date: date
    line_items: list[InvoiceLineItemInput]


@strawberry.input
class ApplyPaymentInput:
    invoice_id: UUID
    external_payment_id: str
    amount_minor: int
    currency: Currency


@strawberry.input
class RecordTransactionInput:
    debit_account_id: UUID
    credit_account_id: UUID
    amount_minor: int
    currency: Currency = Currency.USD
    description: str


@strawberry.type
class Query:
    @strawberry.field
    def accounts(self, info: Info) -> list[AccountTypeOutput]:
        session = _session(info)
        accounts = session.scalars(
            select(Account)
            .options(selectinload(Account.entries).selectinload(LedgerEntry.account))
            .order_by(Account.code)
        ).all()
        return [AccountTypeOutput.from_model(account, session) for account in accounts]

    @strawberry.field
    def account(self, info: Info, id: UUID) -> AccountTypeOutput:
        session = _session(info)
        account = session.scalar(
            select(Account)
            .options(selectinload(Account.entries).selectinload(LedgerEntry.account))
            .where(Account.id == id)
        )
        if not account:
            raise _graphql_error(NotFoundError("Account not found"))
        return AccountTypeOutput.from_model(account, session)

    @strawberry.field
    def account_balance(self, info: Info, account_id: UUID) -> int:
        try:
            return account_balance(_session(info), account_id)
        except DomainError as error:
            raise _graphql_error(error) from error

    @strawberry.field
    def ledger_transactions(self, info: Info) -> list[LedgerTransactionType]:
        transactions = (
            _session(info)
            .scalars(
                select(LedgerTransaction)
                .options(selectinload(LedgerTransaction.entries).selectinload(LedgerEntry.account))
                .order_by(LedgerTransaction.created_at.desc())
            )
            .all()
        )
        return [LedgerTransactionType.from_model(transaction) for transaction in transactions]

    @strawberry.field
    def invoices(self, info: Info) -> list[InvoiceType]:
        invoices = (
            _session(info)
            .scalars(
                select(Invoice).options(*_invoice_options()).order_by(Invoice.created_at.desc())
            )
            .all()
        )
        return [InvoiceType.from_model(invoice) for invoice in invoices]

    @strawberry.field
    def invoice(self, info: Info, id: UUID) -> InvoiceType:
        invoice = _session(info).scalar(
            select(Invoice).options(*_invoice_options()).where(Invoice.id == id)
        )
        if not invoice:
            raise _graphql_error(NotFoundError("Invoice not found"))
        return InvoiceType.from_model(invoice)


@strawberry.type
class Mutation:
    @strawberry.mutation
    def create_account(self, info: Info, input: CreateAccountInput) -> AccountTypeOutput:
        session = _session(info)
        code, name = input.code.strip().upper(), input.name.strip()
        if not code or len(code) > 40 or not name or len(name) > 120:
            raise _graphql_error(DomainError("Invalid account code or name"))
        try:
            with session.begin():
                account = Account(code=code, name=name, type=input.type, currency=input.currency)
                session.add(account)
                session.flush()
            account.entries = []
            return AccountTypeOutput.from_model(account, session)
        except IntegrityError as error:
            raise _graphql_error(ConflictError("Account code already exists")) from error

    @strawberry.mutation
    def create_invoice(self, info: Info, input: CreateInvoiceInput) -> InvoiceType:
        session = _session(info)
        try:
            with session.begin():
                invoice = create_invoice(
                    session,
                    vendor_name=input.vendor_name,
                    currency=input.currency,
                    issue_date=input.issue_date,
                    due_date=input.due_date,
                    line_items=[
                        {
                            "description": item.description,
                            "quantity": item.quantity,
                            "unit_amount_minor": item.unit_amount_minor,
                        }
                        for item in input.line_items
                    ],
                )
            invoice.payments = []
            invoice.ledger_transactions = []
            return InvoiceType.from_model(invoice)
        except DomainError as error:
            raise _graphql_error(error) from error

    @strawberry.mutation
    def record_transaction(
        self, info: Info, input: RecordTransactionInput
    ) -> LedgerTransactionType:
        session = _session(info)
        try:
            with session.begin():
                transaction = record_transfer(
                    session,
                    debit_account_id=input.debit_account_id,
                    credit_account_id=input.credit_account_id,
                    amount_minor=input.amount_minor,
                    currency=input.currency,
                    description=input.description,
                )
            return LedgerTransactionType.from_model(transaction)
        except DomainError as error:
            raise _graphql_error(error) from error

    @strawberry.mutation
    def send_invoice(self, info: Info, invoice_id: UUID) -> InvoiceType:
        session = _session(info)
        try:
            with session.begin():
                send_invoice(session, invoice_id)
            invoice = session.scalar(
                select(Invoice).options(*_invoice_options()).where(Invoice.id == invoice_id)
            )
            assert invoice is not None
            return InvoiceType.from_model(invoice)
        except DomainError as error:
            raise _graphql_error(error) from error

    @strawberry.mutation
    def apply_payment(self, info: Info, input: ApplyPaymentInput) -> InvoiceType:
        session = _session(info)
        try:
            with session.begin():
                apply_payment(
                    session,
                    invoice_id=input.invoice_id,
                    external_payment_id=input.external_payment_id,
                    amount_minor=input.amount_minor,
                    currency=input.currency,
                )
            invoice = session.scalar(
                select(Invoice).options(*_invoice_options()).where(Invoice.id == input.invoice_id)
            )
            assert invoice is not None
            return InvoiceType.from_model(invoice)
        except DomainError as error:
            raise _graphql_error(error) from error


schema = strawberry.Schema(query=Query, mutation=Mutation)
