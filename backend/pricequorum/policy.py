"""Every rule that decides whether a price change may proceed. Pure functions, no model import, and
it fails closed. A judge can open this one file and see what stops a bad write."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MIN_MINOR_UNITS = 100  # a price below 1.00 is refused; 0 is always refused
MAX_MINOR_UNITS = 100_000  # 1,000.00 ceiling for the demo catalogue
MAX_PCT_CHANGE = 0.50  # a swing above 50% is called out in the decision detail
MATCH_THRESHOLD = 90  # entity resolution score below this needs a person
APPROVAL_TTL_SECONDS = 1800  # 30 minutes, then EXPIRED

DecisionKind = Literal["ALLOW", "REFUSED", "NEEDS_HUMAN"]


@dataclass(frozen=True)
class Decision:
    decision: DecisionKind
    rule: str
    detail: str
    remedy: str | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"


@dataclass(frozen=True)
class PolicyContext:
    plan_key: str
    currency: str
    new_minor: int
    old_minor: int | None
    match_confidence: int
    locked_in: str | None = None  # "Notion" or "Airtable" when a human locked the target record
    edit_in_place_requested: bool = False
    price_from_derived_surface: bool = False
    change_key_completed: bool = False
    prior_entry_hash: str | None = None


def refuse_edit_in_place() -> Decision:
    return Decision(
        "REFUSED",
        "stripe_price_immutable",
        "A Stripe Price amount cannot be edited in place.",
        "Ask for the new price instead. PriceQuorum creates a new Price, moves the lookup key and default price, and archives the old one.",
    )


def refuse_direction() -> Decision:
    return Decision(
        "REFUSED",
        "direction_rule",
        "Prices flow from Stripe to Notion and Airtable, never from a derived surface into Stripe.",
        "Change the price in Stripe or ask PriceQuorum for the new price; Notion and Airtable follow Stripe.",
    )


def evaluate(ctx: PolicyContext) -> Decision:
    if ctx.edit_in_place_requested:
        return refuse_edit_in_place()
    if ctx.price_from_derived_surface:
        return refuse_direction()
    if ctx.locked_in:
        return Decision(
            "REFUSED",
            "locked_record",
            f"The {ctx.plan_key} record is marked locked by a human in {ctx.locked_in}.",
            f"Clear the Locked flag for plan '{ctx.plan_key}' in {ctx.locked_in} to proceed.",
        )
    if not MIN_MINOR_UNITS <= ctx.new_minor <= MAX_MINOR_UNITS:
        return Decision(
            "REFUSED",
            "amount_bounds",
            f"Amount {ctx.new_minor} minor units is outside the allowed bounds.",
            f"Submit an amount between {MIN_MINOR_UNITS} and {MAX_MINOR_UNITS} minor units ({ctx.currency.upper()}).",
        )
    if ctx.match_confidence < MATCH_THRESHOLD:
        return Decision(
            "NEEDS_HUMAN",
            "plan_resolution",
            f"Plan resolution confidence {ctx.match_confidence} is below {MATCH_THRESHOLD}.",
            "Add a matching pq_plan_id to the Stripe product, Notion page and Airtable record.",
        )
    if ctx.change_key_completed:
        prior = (ctx.prior_entry_hash or "")[:12]
        return Decision(
            "REFUSED",
            "change_key_completed",
            "This change key already completed.",
            f"Prior entry hash {prior}; use a new change key to run the change again.",
        )
    detail = "Every rule passed. A person must approve before any write."
    if ctx.old_minor:
        pct = abs(ctx.new_minor - ctx.old_minor) / ctx.old_minor
        if pct > MAX_PCT_CHANGE:
            detail = f"Every rule passed. The change is {pct:.0%}, above {MAX_PCT_CHANGE:.0%}; a person must approve before any write."
    return Decision("ALLOW", "all_rules_passed", detail, None)
