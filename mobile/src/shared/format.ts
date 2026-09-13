// GENERATED from web/lib/format.ts by mobile/scripts/sync-shared.mjs.
// Do not edit this copy. Change the web file, then run: npm run sync

/**
 * Display helpers for money and hashes. Amounts arrive as integer minor units and are
 * formatted with string arithmetic, so no float ever touches a displayed price.
 */

// Stripe represents these as two-decimal amounts for backward compatibility, although
// ISO 4217 lists zero decimals (Stripe currencies documentation).
const STRIPE_DIGIT_OVERRIDES: Record<string, number> = { ISK: 2, UGX: 2 };

const digitsCache = new Map<string, number>();

export function currencyDigits(currency: string): number {
  const code = currency.toUpperCase();
  const override = STRIPE_DIGIT_OVERRIDES[code];
  if (override !== undefined) return override;
  const cached = digitsCache.get(code);
  if (cached !== undefined) return cached;
  let digits = 2;
  try {
    digits = new Intl.NumberFormat("en-US", { style: "currency", currency: code }).resolvedOptions().maximumFractionDigits ?? 2;
  } catch {
    digits = 2;
  }
  digitsCache.set(code, digits);
  return digits;
}

/** 2500 usd -> "25.00 USD", 500 jpy -> "500 JPY", 10000 kwd -> "10.000 KWD". */
export function formatMinor(minorUnits: number, currency: string): string {
  if (!Number.isSafeInteger(minorUnits)) return "amount is not an integer";
  const digits = currencyDigits(currency);
  const negative = minorUnits < 0;
  const padded = String(Math.abs(minorUnits)).padStart(digits + 1, "0");
  const whole = digits === 0 ? padded : padded.slice(0, -digits);
  const fraction = digits === 0 ? "" : padded.slice(-digits);
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "-" : ""}${grouped}${fraction ? `.${fraction}` : ""} ${currency.toUpperCase()}`;
}

/** First eight and last four characters, so a hash stays recognisable at a glance. */
export function truncateHash(value: string, head = 8, tail = 4): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}
