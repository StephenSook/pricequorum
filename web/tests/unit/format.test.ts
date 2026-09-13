import { describe, expect, it } from "vitest";

import { currencyDigits, formatMinor, truncateHash } from "@/lib/format";

describe("formatMinor", () => {
  it("formats two-decimal, zero-decimal and three-decimal currencies from integer minor units", () => {
    expect(formatMinor(2500, "usd")).toBe("25.00 USD");
    expect(formatMinor(500, "jpy")).toBe("500 JPY");
    expect(formatMinor(10000, "kwd")).toBe("10.000 KWD");
  });

  it("pads small amounts and groups thousands", () => {
    expect(formatMinor(5, "usd")).toBe("0.05 USD");
    expect(formatMinor(123456789, "usd")).toBe("1,234,567.89 USD");
    expect(formatMinor(-2500, "eur")).toBe("-25.00 EUR");
  });

  it("follows Stripe's two-decimal representation for ISK", () => {
    expect(currencyDigits("isk")).toBe(2);
    expect(formatMinor(10000, "isk")).toBe("100.00 ISK");
  });

  it("refuses to format a non-integer amount instead of rounding it", () => {
    expect(formatMinor(24.999999999999996, "usd")).toBe("amount is not an integer");
  });
});

describe("truncateHash", () => {
  it("keeps the first eight and last four characters", () => {
    expect(truncateHash("3f9a12c4d5e6f708192a3b4c5d6e7f80")).toBe("3f9a12c4…7f80");
  });

  it("leaves short values untouched", () => {
    expect(truncateHash("abc123")).toBe("abc123");
  });
});
