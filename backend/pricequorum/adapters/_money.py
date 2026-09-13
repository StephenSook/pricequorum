"""Conversions between the major-unit numbers Notion and Airtable store and integer minor units.

Every conversion goes through Decimal built from a string, never from a float, so a stored
24.999999999999996 reads back as 2500 minor units rather than 2499.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# ISO 4217 exponents that differ from 2. Stripe follows the same table for these codes.
_ZERO_DECIMAL = {
    "bif",
    "clp",
    "djf",
    "gnf",
    "jpy",
    "kmf",
    "krw",
    "mga",
    "pyg",
    "rwf",
    "ugx",
    "vnd",
    "vuv",
    "xaf",
    "xof",
    "xpf",
}
_THREE_DECIMAL = {"bhd", "jod", "kwd", "omr", "tnd"}


def exponent(currency: str) -> int:
    code = currency.lower()
    if code in _ZERO_DECIMAL:
        return 0
    if code in _THREE_DECIMAL:
        return 3
    return 2


def major_to_minor(value: object, currency: str) -> int | None:
    """Converts a stored major-unit number to minor units. Returns None when the value is not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    return int(amount.scaleb(exponent(currency)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def minor_to_major(minor_units: int, currency: str) -> Decimal:
    return Decimal(minor_units).scaleb(-exponent(currency))


def major_json_number(minor_units: int, currency: str) -> int | float:
    """The JSON number to write for a price: an int when whole, otherwise the exact decimal as a float literal."""
    major = minor_to_major(minor_units, currency)
    if major == major.to_integral_value():
        return int(major)
    return float(major)
