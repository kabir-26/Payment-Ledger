import enum
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class AccountType(str, enum.Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EXPENSE = "EXPENSE"


class Currency(str, enum.Enum):
    USD = "USD"


class Direction(str, enum.Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class InvoiceStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"


class PaymentStatus(str, enum.Enum):
    SUCCEEDED = "SUCCEEDED"


class LedgerEventType(str, enum.Enum):
    INVOICE_POSTED = "INVOICE_POSTED"
    PAYMENT_APPLIED = "PAYMENT_APPLIED"
    MANUAL = "MANUAL"


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[AccountType] = mapped_column(
        Enum(AccountType, name="account_type"), nullable=False
    )
    currency: Mapped[Currency] = mapped_column(Enum(Currency, name="currency"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="account")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("total_amount_minor > 0", name="ck_invoice_total_positive"),
        CheckConstraint("due_date >= issue_date", name="ck_invoice_dates"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    vendor_name: Mapped[str] = mapped_column(String(160), nullable=False)
    currency: Mapped[Currency] = mapped_column(Enum(Currency, name="currency"), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, name="invoice_status"), default=InvoiceStatus.DRAFT, nullable=False
    )
    total_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    line_items: Mapped[list["InvoiceLineItem"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceLineItem.created_at",
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="invoice", order_by="Payment.created_at"
    )
    ledger_transactions: Mapped[list["LedgerTransaction"]] = relationship(back_populates="invoice")


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_line_quantity_positive"),
        CheckConstraint("unit_amount_minor > 0", name="ck_line_unit_positive"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    invoice: Mapped[Invoice] = relationship(back_populates="line_items")

    @property
    def line_total_minor(self) -> int:
        return self.quantity * self.unit_amount_minor


class LedgerTransaction(Base):
    __tablename__ = "ledger_transactions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_reference: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    event_type: Mapped[LedgerEventType] = mapped_column(
        Enum(LedgerEventType, name="ledger_event_type"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    invoice: Mapped[Invoice | None] = relationship(back_populates="ledger_transactions")
    entries: Mapped[list["LedgerEntry"]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="LedgerEntry.created_at",
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (CheckConstraint("amount_minor > 0", name="ck_entry_amount_positive"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ledger_transactions.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    direction: Mapped[Direction] = mapped_column(Enum(Direction, name="direction"), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[Currency] = mapped_column(Enum(Currency, name="currency"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    transaction: Mapped[LedgerTransaction] = relationship(back_populates="entries")
    account: Mapped[Account] = relationship(back_populates="entries")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("external_payment_id", name="uq_payment_external_id"),
        CheckConstraint("amount_minor > 0", name="ck_payment_amount_positive"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    external_payment_id: Mapped[str] = mapped_column(String(180), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[Currency] = mapped_column(Enum(Currency, name="currency"), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), default=PaymentStatus.SUCCEEDED, nullable=False
    )
    ledger_transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ledger_transactions.id"), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    invoice: Mapped[Invoice] = relationship(back_populates="payments")
    ledger_transaction: Mapped[LedgerTransaction] = relationship()


def _prevent_mutation(_mapper: object, _connection: object, _target: object) -> None:
    raise ValueError("Posted ledger records are immutable; create a compensating transaction")


for immutable_model in (LedgerEntry, LedgerTransaction):
    event.listen(immutable_model, "before_update", _prevent_mutation)
    event.listen(immutable_model, "before_delete", _prevent_mutation)
