import { formatMoney, parseMoneyToMinor } from "./money.js";

test("parses currency without floating point arithmetic", () => {
  expect(parseMoneyToMinor("10.01")).toBe(1001);
  expect(parseMoneyToMinor("0.10")).toBe(10);
  expect(parseMoneyToMinor("123")).toBe(12300);
});

test("rejects unsafe or ambiguous currency input", () => {
  expect(() => parseMoneyToMinor("1.001")).toThrow();
  expect(() => parseMoneyToMinor("-1.00")).toThrow();
  expect(() => parseMoneyToMinor("0")).toThrow();
});

test("formats exact minor units", () => {
  expect(formatMoney(1001)).toBe("USD 10.01");
  expect(formatMoney(-10)).toBe("-USD 0.10");
});

