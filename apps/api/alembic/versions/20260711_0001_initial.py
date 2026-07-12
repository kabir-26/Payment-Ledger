"""Initial immutable double-entry ledger schema."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260711_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE account_type AS ENUM ('ASSET', 'LIABILITY', 'EXPENSE')"
    )
    op.execute("CREATE TYPE currency AS ENUM ('USD')")
    op.execute(
        "CREATE TYPE invoice_status AS ENUM ('DRAFT', 'SENT', 'PARTIALLY_PAID', 'PAID', 'OVERDUE')"
    )
    op.execute("CREATE TYPE payment_status AS ENUM ('SUCCEEDED')")
    op.execute("CREATE TYPE direction AS ENUM ('DEBIT', 'CREDIT')")
    op.execute(
        "CREATE TYPE ledger_event_type AS ENUM ('INVOICE_POSTED', 'PAYMENT_APPLIED', 'MANUAL')"
    )
    account_type = postgresql.ENUM(
        "ASSET", "LIABILITY", "EXPENSE", name="account_type", create_type=False
    )
    currency = postgresql.ENUM("USD", name="currency", create_type=False)
    invoice_status = postgresql.ENUM(
        "DRAFT",
        "SENT",
        "PARTIALLY_PAID",
        "PAID",
        "OVERDUE",
        name="invoice_status",
        create_type=False,
    )
    payment_status = postgresql.ENUM("SUCCEEDED", name="payment_status", create_type=False)
    direction = postgresql.ENUM("DEBIT", "CREDIT", name="direction", create_type=False)
    event_type = postgresql.ENUM(
        "INVOICE_POSTED", "PAYMENT_APPLIED", "MANUAL", name="ledger_event_type", create_type=False
    )

    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("type", account_type, nullable=False),
        sa.Column("currency", currency, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("invoice_number", sa.String(40), nullable=False, unique=True),
        sa.Column("vendor_name", sa.String(160), nullable=False),
        sa.Column("currency", currency, nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", invoice_status, nullable=False),
        sa.Column("total_amount_minor", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("total_amount_minor > 0", name="ck_invoice_total_positive"),
        sa.CheckConstraint("due_date >= issue_date", name="ck_invoice_dates"),
    )
    op.create_table(
        "invoice_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id"),
            nullable=False,
        ),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_amount_minor", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_line_quantity_positive"),
        sa.CheckConstraint("unit_amount_minor > 0", name="ck_line_unit_positive"),
    )
    op.create_table(
        "ledger_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_reference", sa.String(180), nullable=False, unique=True),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("invoices.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ledger_transactions.id"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("direction", direction, nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", currency, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="ck_entry_amount_positive"),
    )
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id"),
            nullable=False,
        ),
        sa.Column("external_payment_id", sa.String(180), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", currency, nullable=False),
        sa.Column("status", payment_status, nullable=False),
        sa.Column(
            "ledger_transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ledger_transactions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("external_payment_id", name="uq_payment_external_id"),
        sa.CheckConstraint("amount_minor > 0", name="ck_payment_amount_positive"),
    )
    op.create_index("ix_entries_account_created", "ledger_entries", ["account_id", "created_at"])
    op.create_index("ix_entries_transaction", "ledger_entries", ["transaction_id"])
    op.create_index("ix_payments_invoice_status", "payments", ["invoice_id", "status"])
    op.create_index("ix_ledger_invoice", "ledger_transactions", ["invoice_id"])

    op.execute("""
    CREATE FUNCTION reject_ledger_mutation() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION 'posted ledger records are immutable; post a compensating transaction';
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER ledger_entries_immutable
      BEFORE UPDATE OR DELETE ON ledger_entries
      FOR EACH ROW EXECUTE FUNCTION reject_ledger_mutation();
    CREATE TRIGGER ledger_transactions_immutable
      BEFORE UPDATE OR DELETE ON ledger_transactions
      FOR EACH ROW EXECUTE FUNCTION reject_ledger_mutation();
    """)
    op.execute("""
    CREATE FUNCTION validate_ledger_transaction() RETURNS trigger AS $$
    DECLARE target_id uuid;
    DECLARE entry_count integer;
    DECLARE bad_currency_count integer;
    BEGIN
      IF TG_TABLE_NAME = 'ledger_transactions' THEN
        target_id := NEW.id;
      ELSE
        target_id := COALESCE(NEW.transaction_id, OLD.transaction_id);
      END IF;
      SELECT count(*) INTO entry_count FROM ledger_entries WHERE transaction_id = target_id;
      IF entry_count < 2 THEN
        RAISE EXCEPTION 'ledger transaction % requires at least two entries', target_id;
      END IF;
      SELECT count(*) INTO bad_currency_count FROM (
        SELECT currency,
          sum(CASE WHEN direction = 'DEBIT' THEN amount_minor ELSE 0 END) AS debits,
          sum(CASE WHEN direction = 'CREDIT' THEN amount_minor ELSE 0 END) AS credits
        FROM ledger_entries WHERE transaction_id = target_id GROUP BY currency
      ) totals WHERE debits <> credits;
      IF bad_currency_count > 0 THEN
        RAISE EXCEPTION 'ledger transaction % is not balanced', target_id;
      END IF;
      RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    CREATE CONSTRAINT TRIGGER ledger_transaction_balanced
      AFTER INSERT ON ledger_entries DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW EXECUTE FUNCTION validate_ledger_transaction();
    CREATE CONSTRAINT TRIGGER ledger_header_balanced
      AFTER INSERT ON ledger_transactions DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW EXECUTE FUNCTION validate_ledger_transaction();
    """)
    op.execute("""
    CREATE FUNCTION validate_new_ledger_entry() RETURNS trigger AS $$
    DECLARE header_xid bigint;
    DECLARE account_currency currency;
    BEGIN
      SELECT xmin::text::bigint INTO header_xid
        FROM ledger_transactions WHERE id = NEW.transaction_id;
      IF header_xid IS NULL OR header_xid <> txid_current() THEN
        RAISE EXCEPTION 'entries can only be added while their transaction is being posted';
      END IF;
      SELECT currency INTO account_currency FROM accounts WHERE id = NEW.account_id;
      IF account_currency IS NULL OR account_currency <> NEW.currency THEN
        RAISE EXCEPTION 'ledger entry currency must match account currency';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER ledger_entry_insert_guard
      BEFORE INSERT ON ledger_entries
      FOR EACH ROW EXECUTE FUNCTION validate_new_ledger_entry();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ledger_entry_insert_guard ON ledger_entries")
    op.execute("DROP FUNCTION IF EXISTS validate_new_ledger_entry")
    op.execute("DROP TRIGGER IF EXISTS ledger_header_balanced ON ledger_transactions")
    op.execute("DROP TRIGGER IF EXISTS ledger_transaction_balanced ON ledger_entries")
    op.execute("DROP FUNCTION IF EXISTS validate_ledger_transaction")
    op.execute("DROP TRIGGER IF EXISTS ledger_transactions_immutable ON ledger_transactions")
    op.execute("DROP TRIGGER IF EXISTS ledger_entries_immutable ON ledger_entries")
    op.execute("DROP FUNCTION IF EXISTS reject_ledger_mutation")
    for table in (
        "payments",
        "ledger_entries",
        "ledger_transactions",
        "invoice_line_items",
        "invoices",
        "accounts",
    ):
        op.drop_table(table)
    for enum_name in (
        "ledger_event_type",
        "direction",
        "payment_status",
        "invoice_status",
        "currency",
        "account_type",
    ):
        postgresql.ENUM(name=enum_name).drop(op.get_bind())
