import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, NavLink, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { graphql, INVOICE_FIELDS } from "./api.js";
import { formatMoney, parseMoneyToMinor } from "./money.js";

function useQuery(query, variables = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const key = JSON.stringify(variables);
  const reload = useCallback(() => {
    graphql(query, variables)
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((error) => setState({ data: null, error, loading: false }));
  }, [query, key]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(reload, [reload]);
  return { ...state, reload };
}

function StateMessage({ loading, error, empty = false, children = null }) {
  if (loading) return <div className="state" role="status"><span className="spinner" /> Loading…</div>;
  if (error) return <div className="state error" role="alert"><strong>Couldn’t load data.</strong><br />{error.message}</div>;
  if (empty) return <div className="state">{children || "Nothing here yet."}</div>;
  return null;
}

function Status({ value }) {
  return <span className={`status status-${value.toLowerCase()}`}>{value.replaceAll("_", " ")}</span>;
}

function AppShell({ children }) {
  return <div className="app-shell">
    <aside>
      <Link className="brand" to="/"><span className="brand-mark">W</span><span>Waybill<br /><small>LEDGER</small></span></Link>
      <nav aria-label="Primary navigation">
        <NavLink end to="/">Overview</NavLink>
        <NavLink to="/accounts">Accounts</NavLink>
        <NavLink to="/invoices">Invoices</NavLink>
        <NavLink to="/ledger">General ledger</NavLink>
      </nav>
      <div className="aside-note"><span className="live-dot" /> Local environment<br /><small>USD · Double entry</small></div>
    </aside>
    <main>{children}</main>
  </div>;
}

const OVERVIEW_QUERY = `query Overview {
  invoices { id status totalAmountMinor totalPaidMinor outstandingAmountMinor dueDate currency }
  accounts { id code name type currency balanceMinor }
}`;

function Dashboard() {
  const { data, loading, error } = useQuery(OVERVIEW_QUERY);
  const cards = useMemo(() => ({
    unpaid: (data?.invoices || []).reduce((sum, item) => sum + (item.status === "DRAFT" ? 0 : item.outstandingAmountMinor), 0),
    drafts: (data?.invoices || []).filter((item) => item.status === "DRAFT").length,
    active: (data?.invoices || []).filter((item) => ["SENT", "PARTIALLY_PAID"].includes(item.status)).length,
    overdue: (data?.invoices || []).filter((item) => item.status === "OVERDUE").length,
  }), [data]);
  return <Page title="Accounts payable" eyebrow="Operations overview" action={<Link className="button primary" to="/invoices/new">New invoice</Link>}>
    <StateMessage loading={loading} error={error} />
    {data && <>
      <section className="metric-grid" aria-label="Invoice summary">
        <article className="metric featured"><span>Unpaid posted invoices</span><strong>{formatMoney(cards.unpaid)}</strong><small>Outstanding liability</small></article>
        <article className="metric"><span>Draft invoices</span><strong>{cards.drafts}</strong><small>Awaiting posting</small></article>
        <article className="metric"><span>Open invoices</span><strong>{cards.active}</strong><small>Sent or partially paid</small></article>
        <article className="metric"><span>Overdue</span><strong>{cards.overdue}</strong><small>Past due and unpaid</small></article>
      </section>
      <section className="panel">
        <div className="panel-heading"><div><span className="eyebrow">Derived balances</span><h2>System accounts</h2></div><Link to="/ledger">Inspect entries →</Link></div>
        <div className="account-grid">
          {data.accounts.map((account) => <article className="account" key={account.id}>
            <span className="account-icon">{account.type === "ASSET" ? "B" : account.type === "LIABILITY" ? "L" : "E"}</span>
            <div><small>{account.code}</small><h3>{account.name}</h3><strong>{formatMoney(account.balanceMinor, account.currency)}</strong></div>
          </article>)}
        </div>
      </section>
    </>}
  </Page>;
}

const INVOICES_QUERY = `query Invoices { invoices { ${INVOICE_FIELDS} } }`;

const ACCOUNTS_QUERY = `query Accounts {
  accounts { id code name type currency balanceMinor }
}`;

function Accounts() {
  const { data, loading, error, reload } = useQuery(ACCOUNTS_QUERY);
  const [account, setAccount] = useState({ code: "", name: "", type: "ASSET" });
  const [transaction, setTransaction] = useState({
    debitAccountId: "", creditAccountId: "", amount: "", description: "",
  });
  const [actionError, setActionError] = useState(null);
  const [saving, setSaving] = useState(false);

  async function createAccount(event) {
    event.preventDefault(); setSaving(true); setActionError(null);
    try {
      await graphql(`mutation CreateAccount($input: CreateAccountInput!) {
        createAccount(input: $input) { id }
      }`, { input: { ...account, currency: "USD" } });
      setAccount({ code: "", name: "", type: "ASSET" }); reload();
    } catch (caught) { setActionError(caught); } finally { setSaving(false); }
  }

  async function recordTransaction(event) {
    event.preventDefault(); setSaving(true); setActionError(null);
    try {
      await graphql(`mutation Record($input: RecordTransactionInput!) {
        recordTransaction(input: $input) { id }
      }`, { input: {
        debitAccountId: transaction.debitAccountId,
        creditAccountId: transaction.creditAccountId,
        amountMinor: parseMoneyToMinor(transaction.amount),
        currency: "USD",
        description: transaction.description,
      } });
      setTransaction({ debitAccountId: "", creditAccountId: "", amount: "", description: "" });
      reload();
    } catch (caught) { setActionError(caught); } finally { setSaving(false); }
  }

  const accounts = data?.accounts || [];
  return <Page title="Accounts" eyebrow="Double-entry ledger">
    <StateMessage loading={loading} error={error} />
    {actionError && <div className="alert" role="alert">{actionError.message}</div>}
    {data && <>
      <section className="panel">
        <div className="panel-heading"><h2>Account balances</h2><span>Derived from entries</span></div>
        <div className="account-grid">{accounts.map((item) => <article className="account" key={item.id}>
          <span className="account-icon">{item.type[0]}</span><div><small>{item.code}</small><h3>{item.name}</h3><strong>{formatMoney(item.balanceMinor)}</strong></div>
        </article>)}</div>
      </section>
      <div className="detail-grid">
        <form className="panel action-panel" onSubmit={createAccount}>
          <h2>Create account</h2>
          <label>Code<input required maxLength={40} value={account.code} onChange={(e) => setAccount({ ...account, code: e.target.value })} placeholder="FUEL_EXPENSE" /></label>
          <label>Name<input required maxLength={120} value={account.name} onChange={(e) => setAccount({ ...account, name: e.target.value })} placeholder="Fuel Expense" /></label>
          <label>Type<select value={account.type} onChange={(e) => setAccount({ ...account, type: e.target.value })}>{["ASSET", "LIABILITY", "EXPENSE"].map((type) => <option key={type}>{type}</option>)}</select></label>
          <button disabled={saving} className="button primary full">Create account</button>
        </form>
        <form className="panel action-panel" onSubmit={recordTransaction}>
          <h2>Record transaction</h2>
          <label>Description<input required maxLength={240} value={transaction.description} onChange={(e) => setTransaction({ ...transaction, description: e.target.value })} placeholder="Record expense" /></label>
          <label>Debit account<select required value={transaction.debitAccountId} onChange={(e) => setTransaction({ ...transaction, debitAccountId: e.target.value })}><option value="">Select…</option>{accounts.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
          <label>Credit account<select required value={transaction.creditAccountId} onChange={(e) => setTransaction({ ...transaction, creditAccountId: e.target.value })}><option value="">Select…</option>{accounts.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
          <label>Amount (USD)<input required inputMode="decimal" value={transaction.amount} onChange={(e) => setTransaction({ ...transaction, amount: e.target.value })} placeholder="0.00" /></label>
          <button disabled={saving} className="button primary full">Record debit & credit</button>
        </form>
      </div>
    </>}
  </Page>;
}

function InvoiceList() {
  const { data, loading, error } = useQuery(INVOICES_QUERY);
  return <Page title="Invoices" eyebrow="Accounts payable" action={<Link className="button primary" to="/invoices/new">New invoice</Link>}>
    <div className="panel table-panel">
      <StateMessage loading={loading} error={error} empty={data?.invoices.length === 0}>Create the first invoice to begin the workflow.</StateMessage>
      {data?.invoices.length > 0 && <div className="table-scroll"><table>
        <thead><tr><th>Invoice</th><th>Vendor</th><th>Due</th><th>Total</th><th>Paid</th><th>Outstanding</th><th>Status</th></tr></thead>
        <tbody>{data.invoices.map((invoice) => <tr key={invoice.id}>
          <td><Link className="strong-link" to={`/invoices/${invoice.id}`}>{invoice.invoiceNumber}</Link></td>
          <td>{invoice.vendorName}</td><td>{invoice.dueDate}</td>
          <td>{formatMoney(invoice.totalAmountMinor, invoice.currency)}</td>
          <td>{formatMoney(invoice.totalPaidMinor, invoice.currency)}</td>
          <td className="strong-cell">{formatMoney(invoice.outstandingAmountMinor, invoice.currency)}</td>
          <td><Status value={invoice.status} /></td>
        </tr>)}</tbody>
      </table></div>}
    </div>
  </Page>;
}

function CreateInvoice() {
  const navigate = useNavigate();
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({ vendorName: "", issueDate: today, dueDate: today });
  const [items, setItems] = useState([{ description: "", quantity: 1, amount: "" }]);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const minorItems = useMemo(() => items.map((item) => {
    try { return { ...item, minor: parseMoneyToMinor(item.amount) }; } catch { return { ...item, minor: 0 }; }
  }), [items]);
  const total = minorItems.reduce((sum, item) => sum + item.quantity * item.minor, 0);
  const updateItem = (index, patch) => setItems((old) => old.map((item, i) => i === index ? { ...item, ...patch } : item));
  async function submit(event) {
    event.preventDefault(); setError(null); setSaving(true);
    try {
      const lineItems = items.map((item) => ({
        description: item.description,
        quantity: Number(item.quantity),
        unitAmountMinor: parseMoneyToMinor(item.amount),
      }));
      const data = await graphql(`mutation Create($input: CreateInvoiceInput!) {
        createInvoice(input: $input) { id }
      }`, { input: { ...form, currency: "USD", lineItems } });
      navigate(`/invoices/${data.createInvoice.id}`);
    } catch (caught) { setError(caught); } finally { setSaving(false); }
  }
  return <Page title="Create invoice" eyebrow="New draft">
    <form className="panel form-panel" onSubmit={submit}>
      {error && <div className="alert" role="alert">{error.message}</div>}
      <div className="field-grid">
        <label className="wide">Vendor / payee<span>Required</span><input required maxLength={160} value={form.vendorName} onChange={(e) => setForm({ ...form, vendorName: e.target.value })} placeholder="e.g. North Star Freight" /></label>
        <label>Issue date<input required type="date" value={form.issueDate} onChange={(e) => setForm({ ...form, issueDate: e.target.value })} /></label>
        <label>Due date<input required type="date" min={form.issueDate} value={form.dueDate} onChange={(e) => setForm({ ...form, dueDate: e.target.value })} /></label>
      </div>
      <div className="line-heading"><div><span className="eyebrow">Charges</span><h2>Line items</h2></div><button type="button" className="button secondary" onClick={() => setItems([...items, { description: "", quantity: 1, amount: "" }])}>Add line</button></div>
      <div className="line-items">{items.map((item, index) => <div className="line-item" key={index}>
        <label>Description<input required maxLength={240} value={item.description} onChange={(e) => updateItem(index, { description: e.target.value })} placeholder="Linehaul service" /></label>
        <label>Qty<input required type="number" min="1" step="1" value={item.quantity} onChange={(e) => updateItem(index, { quantity: Number(e.target.value) })} /></label>
        <label>Unit price (USD)<input required inputMode="decimal" value={item.amount} onChange={(e) => updateItem(index, { amount: e.target.value })} placeholder="0.00" /></label>
        <button aria-label={`Remove line ${index + 1}`} disabled={items.length === 1} type="button" className="remove" onClick={() => setItems(items.filter((_, i) => i !== index))}>×</button>
      </div>)}</div>
      <div className="form-total"><span>Server will recalculate the total</span><strong>{formatMoney(total)}</strong></div>
      <div className="form-actions"><Link className="button secondary" to="/invoices">Cancel</Link><button disabled={saving} className="button primary" type="submit">{saving ? "Creating…" : "Create draft"}</button></div>
    </form>
  </Page>;
}

const INVOICE_QUERY = `query Invoice($id: UUID!) { invoice(id: $id) { ${INVOICE_FIELDS} } }`;

function InvoiceDetail() {
  const { id } = useParams();
  const { data, loading, error, reload } = useQuery(INVOICE_QUERY, { id });
  const [actionError, setActionError] = useState(null);
  const [working, setWorking] = useState(false);
  const [payment, setPayment] = useState({ amount: "", externalPaymentId: `manual-${crypto.randomUUID()}` });
  const invoice = data?.invoice;
  async function send() {
    setWorking(true); setActionError(null);
    try { await graphql(`mutation Send($id: UUID!) { sendInvoice(invoiceId: $id) { id } }`, { id }); reload(); }
    catch (caught) { setActionError(caught); } finally { setWorking(false); }
  }
  async function pay(event) {
    event.preventDefault(); setWorking(true); setActionError(null);
    try {
      await graphql(`mutation Pay($input: ApplyPaymentInput!) { applyPayment(input: $input) { id } }`, {
        input: { invoiceId: id, externalPaymentId: payment.externalPaymentId, amountMinor: parseMoneyToMinor(payment.amount), currency: "USD" },
      });
      reload();
    } catch (caught) { setActionError(caught); } finally { setWorking(false); }
  }
  return <Page title={invoice?.invoiceNumber || "Invoice"} eyebrow="Invoice detail" action={<Link className="button secondary" to="/invoices">Back to invoices</Link>}>
    <StateMessage loading={loading} error={error} />
    {invoice && <>
      {actionError && <div className="alert" role="alert"><strong>{actionError.code || "ERROR"}</strong> · {actionError.message}</div>}
      <section className="invoice-hero panel">
        <div><Status value={invoice.status} /><h2>{invoice.vendorName}</h2><p>Issued {invoice.issueDate} · Due {invoice.dueDate}</p></div>
        <div className="amount-due"><span>Outstanding</span><strong>{formatMoney(invoice.outstandingAmountMinor, invoice.currency)}</strong><small>of {formatMoney(invoice.totalAmountMinor, invoice.currency)}</small></div>
      </section>
      <div className="detail-grid">
        <section className="panel"><div className="panel-heading"><h2>Line items</h2></div>
          <div className="table-scroll"><table><thead><tr><th>Description</th><th>Qty</th><th>Unit</th><th>Total</th></tr></thead><tbody>
            {invoice.lineItems.map((line) => <tr key={line.id}><td>{line.description}</td><td>{line.quantity}</td><td>{formatMoney(line.unitAmountMinor)}</td><td className="strong-cell">{formatMoney(line.lineTotalMinor)}</td></tr>)}
          </tbody></table></div>
        </section>
        <aside className="panel action-panel">
          {invoice.status === "DRAFT" ? <><h2>Ready to post?</h2><p>Sending debits Freight Expense and credits Accounts Payable. This cannot be silently undone.</p><button className="button primary full" disabled={working} onClick={send}>Send & post invoice</button></> : invoice.outstandingAmountMinor > 0 ? <form onSubmit={pay}>
            <h2>Apply payment</h2><label>Amount (USD)<input required inputMode="decimal" value={payment.amount} onChange={(e) => setPayment({ ...payment, amount: e.target.value })} placeholder={(invoice.outstandingAmountMinor / 100).toFixed(2)} /></label>
            <label>External payment ID<span>Keep this value to replay safely</span><input required maxLength={180} value={payment.externalPaymentId} onChange={(e) => setPayment({ ...payment, externalPaymentId: e.target.value })} /></label>
            <button className="button primary full" disabled={working} type="submit">Apply payment</button>
          </form> : <><h2>Invoice settled</h2><p>Successful payments exactly match the posted invoice total.</p><div className="settled">✓ Paid in full</div></>}
        </aside>
      </div>
      <section className="panel"><div className="panel-heading"><h2>Payment history</h2><span>{invoice.payments.length} payment{invoice.payments.length === 1 ? "" : "s"}</span></div>
        {invoice.payments.length === 0 ? <div className="state compact">No payments applied.</div> : <div className="table-scroll"><table><thead><tr><th>External ID</th><th>Date</th><th>Amount</th><th>Status</th></tr></thead><tbody>{invoice.payments.map((item) => <tr key={item.id}><td className="mono">{item.externalPaymentId}</td><td>{new Date(item.createdAt).toLocaleString()}</td><td>{formatMoney(item.amountMinor)}</td><td><Status value={item.status} /></td></tr>)}</tbody></table></div>}
      </section>
      <TransactionList transactions={invoice.ledgerTransactions} />
    </>}
  </Page>;
}

const LEDGER_QUERY = `query Ledger { ledgerTransactions { id externalReference description eventType invoiceId createdAt entries { id direction amountMinor currency account { id code name } } } }`;

function TransactionList({ transactions }) {
  return <section className="ledger-list">
    {transactions.map((transaction) => {
      const debits = transaction.entries.filter((e) => e.direction === "DEBIT").reduce((sum, e) => sum + e.amountMinor, 0);
      const credits = transaction.entries.filter((e) => e.direction === "CREDIT").reduce((sum, e) => sum + e.amountMinor, 0);
      return <article className="panel transaction" key={transaction.id}>
        <header><div><span className="eyebrow">{transaction.eventType.replaceAll("_", " ")}</span><h2>{transaction.description}</h2><small className="mono">{transaction.externalReference}</small></div><span className={`balance-check ${debits === credits ? "ok" : "bad"}`}>{debits === credits ? "✓ Balanced" : "! Unbalanced"}</span></header>
        <div className="entries">{transaction.entries.map((entry) => <div className="entry" key={entry.id}><span className={`direction ${entry.direction.toLowerCase()}`}>{entry.direction}</span><div><strong>{entry.account.name}</strong><small>{entry.account.code}</small></div><strong>{formatMoney(entry.amountMinor, entry.currency)}</strong></div>)}</div>
      </article>;
    })}
  </section>;
}

function Ledger() {
  const { data, loading, error } = useQuery(LEDGER_QUERY);
  return <Page title="General ledger" eyebrow="Immutable entry history">
    <StateMessage loading={loading} error={error} empty={data?.ledgerTransactions.length === 0}>Posting an invoice creates the first transaction.</StateMessage>
    {data && <TransactionList transactions={data.ledgerTransactions} />}
  </Page>;
}

function Page({ title, eyebrow, action = null, children }) {
  return <><header className="page-header"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1></div>{action}</header><div className="page-body">{children}</div></>;
}

export default function App() {
  return <AppShell><Routes>
    <Route path="/" element={<Dashboard />} />
    <Route path="/accounts" element={<Accounts />} />
    <Route path="/invoices" element={<InvoiceList />} />
    <Route path="/invoices/new" element={<CreateInvoice />} />
    <Route path="/invoices/:id" element={<InvoiceDetail />} />
    <Route path="/ledger" element={<Ledger />} />
    <Route path="*" element={<Page title="Page not found" eyebrow="404"><Link to="/">Return to overview</Link></Page>} />
  </Routes></AppShell>;
}
