# Simple Payment Ledger

A small ledger and invoice application with a FastAPI/GraphQL backend and React UI.

## What it does

- Create asset, liability, and expense accounts.
- Record a transaction by choosing one debit account and one credit account.
- Derive every balance from immutable ledger entries; balances are never stored separately.
- Store money as integer cents.
- Create draft invoices with line items and a due date.
- Send an invoice, then apply partial or full payments.
- Prevent overpayment.
- Treat repeated payment IDs as idempotent: the same payment is returned once, while changed data is rejected.
- Show draft, sent, partially paid, paid, and overdue states.

Invoice posting debits Freight Expense and credits Accounts Payable. Payments debit Accounts Payable and credit Operating Bank.

## Run locally without Docker

Prerequisites: Python 3.12+ and Node.js 22+.

From PowerShell in the repository root:

```powershell
Copy-Item .env.example .env
py -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r apps/api/requirements-dev.txt
& "C:\Program Files\nodejs\npm.cmd" ci --prefix apps/web
```

Start the API in one PowerShell window:

```powershell
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --app-dir apps/api
```

Start the UI in another:

```powershell
& "C:\Program Files\nodejs\npm.cmd" run dev --prefix apps/web
```

Open:

- UI: [http://localhost:5173](http://localhost:5173)
- GraphQL: [http://localhost:8000/graphql](http://localhost:8000/graphql)

Local mode uses `ledger.db`, creates its schema automatically, and seeds Operating Bank, Accounts Payable, and Freight Expense. Delete `ledger.db` only when you intentionally want a fresh local ledger.

## Docker

Docker is optional. It runs the same app with PostgreSQL:

```powershell
docker compose up --build
```

## Tests

The fast tests cover balanced entries, derived balances, exact cents, manual debit/credit transactions, invoice posting, partial/final payments, overpayment, and duplicate payment IDs.

```powershell
& ".\.venv\Scripts\python.exe" -m pytest apps/api/tests
& "C:\Program Files\nodejs\npm.cmd" test --prefix apps/web -- --runInBand
```

Quality checks:

```powershell
& ".\.venv\Scripts\python.exe" -m ruff check apps/api
& ".\.venv\Scripts\python.exe" -m mypy apps/api/app
& "C:\Program Files\nodejs\npm.cmd" run lint --prefix apps/web
& "C:\Program Files\nodejs\npm.cmd" run typecheck --prefix apps/web
& "C:\Program Files\nodejs\npm.cmd" run build --prefix apps/web
```

## Hosted UI

Hosted UI: **not deployed yet**. A live URL requires access to the owner's hosting account.

For a permanent free demo, use Neon Free for PostgreSQL and Render Free for the
API and UI. Do not use Render's free PostgreSQL for this project because it
expires after 30 days.

The included `render.yaml` deploys the API, PostgreSQL-backed configuration, and static UI on Render. After the repository is pushed to GitHub:

1. Create a Render Blueprint from the repository.
2. Set the API `DATABASE_URL` and `CORS_ORIGINS`.
3. Set the UI `VITE_GRAPHQL_URL` to the deployed API URL plus `/graphql`.
4. Replace this section with the generated Render UI URL.

The UI can also be deployed from `apps/web` to Vercel using `apps/web/vercel.json`.

## Shortcuts taken

- USD only.
- Integer line-item quantities only.
- One fixed expense account is used when invoices are sent.
- Payments have only a successful state.
- Overdue status is calculated when invoices are queried rather than by a scheduled job.
- No authentication, authorization, or approval workflow.

## With more time

Add authentication and roles, invoice approvals, signed payment webhooks, reversals/refunds, reconciliation, pagination, audit exports, observability, and end-to-end browser tests. PostgreSQL would remain the production database for stronger concurrent-payment locking.
