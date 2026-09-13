"""Entity resolution: one plan across Stripe, Notion and Airtable.

Deterministic first (a shared pq_plan_id scores 100), fuzzy only as a fallback (rapidfuzz
token_sort_ratio at 90 or above), and anything ambiguous or low-confidence goes to a person.
A plan-plus-currency pair is the atomic unit, so two currencies of one plan never merge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from pricequorum.policy import MATCH_THRESHOLD
from pricequorum.ports import PlanRecord

REMEDY = "Add a matching pq_plan_id to the Stripe product, Notion page and Airtable record."

_INTERVALS = {
    "monthly": "month",
    "mo": "month",
    "month": "month",
    "months": "month",
    "yearly": "year",
    "annual": "year",
    "annually": "year",
    "year": "year",
    "years": "year",
    "yr": "year",
}
_CURRENCIES = {
    "usd": "usd",
    "dollar": "usd",
    "dollars": "usd",
    "eur": "eur",
    "euro": "eur",
    "euros": "eur",
    "gbp": "gbp",
    "pound": "gbp",
    "pounds": "gbp",
}
_NOISE = {"the", "plan", "tier", "inc", "llc", "ltd", "price", "pricing"}


def normalize(text: str) -> str:
    lowered = text.lower().replace("$", " usd ").replace("€", " eur ").replace("£", " gbp ")
    tokens = []
    for token in re.sub(r"[^a-z0-9 ]+", " ", lowered).split():
        if token in _NOISE:
            continue
        tokens.append(_INTERVALS.get(token, _CURRENCIES.get(token, token)))
    return " ".join(tokens)


def key_of(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass(frozen=True)
class Resolution:
    resolved: bool
    plan_key: str | None
    stripe: PlanRecord | None
    notion: PlanRecord | None
    airtable: PlanRecord | None
    confidence: int
    decided_by: str  # exact_id | fuzzy | human
    detail: str
    remedy: str | None
    candidates: list[dict[str, object]] = field(default_factory=list)


def _in_currency(record: PlanRecord, currency: str) -> bool:
    return record.price is None or record.price.currency == currency


def _stripe_score(target: str, record: PlanRecord, interval: str, currency: str) -> int:
    record_currency = record.price.currency if record.price else currency
    return round(
        fuzz.token_sort_ratio(target, f"{normalize(record.label)} {record.interval or interval} {record_currency}")
    )


def _pick_derived(
    records: list[PlanRecord], stripe: PlanRecord, currency: str
) -> tuple[PlanRecord | None, int, list[tuple[PlanRecord, int]]]:
    scoped = [record for record in records if _in_currency(record, currency)]
    if stripe.pq_plan_id:
        exact = [
            record for record in scoped if record.pq_plan_id and key_of(record.pq_plan_id) == key_of(stripe.pq_plan_id)
        ]
        if len(exact) == 1:
            return exact[0], 100, [(exact[0], 100)]
        if len(exact) > 1:
            return None, 0, [(record, 100) for record in exact]
    target = f"{normalize(stripe.label)} {currency}"
    scored = [
        (
            record,
            round(
                fuzz.token_sort_ratio(
                    target, f"{normalize(record.label)} {record.price.currency if record.price else currency}"
                )
            ),
        )
        for record in scoped
    ]
    good = [item for item in scored if item[1] >= MATCH_THRESHOLD]
    if len(good) == 1:
        return good[0][0], good[0][1], scored
    return None, max((score for _, score in scored), default=0), scored


def resolve(
    plan_hint: str,
    currency: str,
    interval: str,
    stripe_plans: list[PlanRecord],
    notion_plans: list[PlanRecord],
    airtable_plans: list[PlanRecord],
) -> Resolution:
    target = f"{normalize(plan_hint)} {interval} {currency}"
    scoped = [
        plan
        for plan in stripe_plans
        if plan.price is not None and plan.price.currency == currency and plan.interval in (None, interval)
    ]
    exact = [plan for plan in scoped if plan.pq_plan_id and key_of(plan.pq_plan_id) == key_of(plan_hint)]
    candidates: list[dict[str, object]] = [
        {
            "app": "stripe",
            "label": plan.label,
            "score": 100 if plan in exact else _stripe_score(target, plan, interval, currency),
        }
        for plan in stripe_plans
    ]

    def unresolved(detail: str, confidence: int) -> Resolution:
        return Resolution(False, None, None, None, None, confidence, "human", detail, REMEDY, candidates)

    if len(exact) == 1:
        stripe, stripe_score, decided_by = exact[0], 100, "exact_id"
    elif len(exact) > 1:
        return unresolved(f"{len(exact)} Stripe products share pq_plan_id '{plan_hint}' in {currency.upper()}.", 0)
    else:
        fuzzy = [(plan, _stripe_score(target, plan, interval, currency)) for plan in scoped]
        good = [item for item in fuzzy if item[1] >= MATCH_THRESHOLD]
        if len(good) != 1:
            best = max((score for _, score in fuzzy), default=0)
            reason = "No Stripe plan" if not good else f"{len(good)} Stripe plans"
            return unresolved(
                f"{reason} matched '{plan_hint}' ({interval}, {currency.upper()}) at {MATCH_THRESHOLD} or above.", best
            )
        stripe, stripe_score = good[0]
        decided_by = "fuzzy"

    notion, notion_score, notion_scored = _pick_derived(notion_plans, stripe, currency)
    airtable, airtable_score, airtable_scored = _pick_derived(airtable_plans, stripe, currency)
    candidates += [{"app": "notion", "label": record.label, "score": score} for record, score in notion_scored]
    candidates += [{"app": "airtable", "label": record.label, "score": score} for record, score in airtable_scored]

    if notion is None or airtable is None:
        missing = " and ".join(name for name, record in (("Notion", notion), ("Airtable", airtable)) if record is None)
        return Resolution(
            False,
            stripe.pq_plan_id or key_of(stripe.label),
            stripe,
            notion,
            airtable,
            min(stripe_score, notion_score, airtable_score),
            "human",
            f"Stripe plan '{stripe.label}' has no single matching record in {missing}.",
            REMEDY,
            candidates,
        )

    confidence = min(stripe_score, notion_score, airtable_score)
    if decided_by == "exact_id" and confidence < 100:
        decided_by = "fuzzy"
    return Resolution(
        True,
        stripe.pq_plan_id or key_of(stripe.label),
        stripe,
        notion,
        airtable,
        confidence,
        decided_by,
        f"Resolved '{plan_hint}' to Stripe {stripe.external_id}, Notion {notion.external_id}, Airtable {airtable.external_id}.",
        None,
        candidates,
    )


@dataclass(frozen=True)
class PairMatch:
    match: bool
    score: int
    decision: str  # fuzzy | human | different_currency | different_interval
    detail: str


def match_pair(
    left_label: str,
    left_currency: str,
    left_interval: str,
    right_label: str,
    right_currency: str,
    right_interval: str,
) -> PairMatch:
    """Whether two plan records name the same plan, by the rules resolve() applies to one candidate: another
    currency or billing interval never matches, and labels match at MATCH_THRESHOLD or above on the same score
    resolve() computes. resolve() also needs exactly one candidate to clear the bar, which one pair cannot show."""
    currency, other_currency = left_currency.strip().lower(), right_currency.strip().lower()
    interval = _INTERVALS.get(left_interval.strip().lower(), left_interval.strip().lower())
    other_interval = _INTERVALS.get(right_interval.strip().lower(), right_interval.strip().lower())
    if currency != other_currency:
        return PairMatch(
            False,
            0,
            "different_currency",
            f"{currency.upper()} and {other_currency.upper()} are separate plans; currencies never merge.",
        )
    if interval and other_interval and interval != other_interval:
        return PairMatch(
            False, 0, "different_interval", f"A {interval} plan and a {other_interval} plan are separate plans."
        )
    shared_interval = interval or other_interval or "month"
    record = PlanRecord(
        app="stripe",
        external_id="pair",
        pq_plan_id=None,
        label=right_label,
        price=None,
        raw_value=None,
        interval=None,
        locked=False,
    )
    score = _stripe_score(f"{normalize(left_label)} {shared_interval} {currency}", record, shared_interval, currency)
    matched = score >= MATCH_THRESHOLD
    return PairMatch(
        matched,
        score,
        "fuzzy" if matched else "human",
        f"Label score {score} against the threshold {MATCH_THRESHOLD}.",
    )
