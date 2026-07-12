export function parseMoneyToMinor(value) {
  const normalized = String(value).trim();
  const match = /^(\d+)(?:\.(\d{1,2}))?$/.exec(normalized);
  if (!match) throw new Error("Enter a positive amount with at most two decimal places");
  const minor = BigInt(match[1]) * 100n + BigInt((match[2] || "").padEnd(2, "0"));
  if (minor <= 0n || minor > 2_147_483_647n) throw new Error("Amount is outside the supported range");
  return Number(minor);
}

export function formatMoney(amountMinor, currency = "USD") {
  const sign = amountMinor < 0 ? "-" : "";
  const absolute = Math.abs(amountMinor);
  const major = Math.floor(absolute / 100);
  const minor = String(absolute % 100).padStart(2, "0");
  return `${sign}${currency} ${major.toLocaleString("en-US")}.${minor}`;
}

