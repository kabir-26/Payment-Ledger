const endpoint = import.meta.env.VITE_GRAPHQL_URL || "http://localhost:8000/graphql";

export async function graphql(query, variables = {}) {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, variables }),
  });
  if (!response.ok) throw new Error(`API request failed (${response.status})`);
  const body = await response.json();
  if (body.errors?.length) {
    const error = Object.assign(new Error(body.errors[0].message), {
      code: body.errors[0].extensions?.code,
    });
    throw error;
  }
  return body.data;
}

export const INVOICE_FIELDS = `
  id invoiceNumber vendorName currency issueDate dueDate status
  totalAmountMinor totalPaidMinor outstandingAmountMinor version createdAt
  lineItems { id description quantity unitAmountMinor lineTotalMinor }
  payments { id externalPaymentId amountMinor currency status createdAt ledgerTransactionId }
  ledgerTransactions {
    id externalReference description eventType createdAt
    entries { id direction amountMinor currency account { id code name } }
  }
`;
