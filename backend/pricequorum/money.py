"""Money as integer minor units plus a currency. No float ever crosses a module boundary.

Notion and Airtable store prices as IEEE-754 doubles, so 25.00 can arrive as 24.999999999999996.
Convert through str() into Decimal first (Decimal(float) inherits the float error), then round to
the currency's minor unit and compare integers only.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from pricequorum.ports import Money

# ISO 4217 exponents. Stripe represents ISK and UGX as two-decimal amounts for backward compatibility.
EXPONENTS: dict[str, int] = {
    "usd": 2,
    "eur": 2,
    "gbp": 2,
    "cad": 2,
    "aud": 2,
    "chf": 2,
    "sek": 2,
    "nok": 2,
    "dkk": 2,
    "inr": 2,
    "brl": 2,
    "mxn": 2,
    "sgd": 2,
    "hkd": 2,
    "nzd": 2,
    "isk": 2,
    "ugx": 2,
    "jpy": 0,
    "krw": 0,
    "vnd": 0,
    "clp": 0,
    "kwd": 3,
    "bhd": 3,
    "omr": 3,
    "jod": 3,
    "tnd": 3,
}


def exponent(currency: str) -> int:
    code = currency.lower()
    if code not in EXPONENTS:
        raise ValueError(f"unsupported currency {currency!r}")
    return EXPONENTS[code]


def to_minor_units(human_value: object, currency: str) -> int:
    """A human amount (Notion or Airtable number, or typed text) to exact integer minor units."""
    if isinstance(human_value, bool):
        raise TypeError("a boolean is not an amount")
    try:
        value = Decimal(str(human_value).replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {human_value!r}") from exc
    if not value.is_finite():
        raise ValueError(f"not a finite number: {human_value!r}")
    return int(value.scaleb(exponent(currency)).to_integral_value(rounding=ROUND_HALF_UP))


def to_human(minor_units: int, currency: str) -> Decimal:
    """Integer minor units to the exact decimal a person reads."""
    return Decimal(minor_units).scaleb(-exponent(currency))


def money_from_human(human_value: object, currency: str) -> Money:
    return Money(to_minor_units(human_value, currency), currency.lower())


def format_money(amount: Money) -> str:
    digits = exponent(amount.currency)
    return f"{to_human(amount.minor_units, amount.currency):.{digits}f} {amount.currency.upper()}"


def amounts_agree(amounts: list[Money | None]) -> bool:
    """True only when every amount is present and all are equal in minor units and currency."""
    if not amounts or any(amount is None for amount in amounts):
        return False
    first = amounts[0]
    return all(amount == first for amount in amounts)
