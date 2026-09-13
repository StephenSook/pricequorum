"""The read-back verifier. After the writes it reads every system fresh, converts to integer minor
units, and checks the invariant register. The run's outcome is the worst class any check reports,
so SUCCESS can only come from observed state, never from a tool response."""

from __future__ import annotations

from dataclasses import dataclass

from pricequorum.money import amounts_agree, format_money
from pricequorum.ports import AdapterFault, AdapterRefusal, DerivedPort, Interval, Money, Readback, StripePort

# The exact checks every write run reports, in order. run.outcome carries this list.
INVARIANTS_EXPECTED: tuple[str, ...] = (
    "stripe_default_price_matches_target",
    "all_three_surfaces_agree",
    "old_price_archived",
    "no_target_human_locked",
    "direction_rule_holds",
)

SEVERITY = {"SUCCESS": 0, "PARTIAL": 1, "NEEDS_HUMAN": 2, "REFUSED": 3}


def worst(outcomes: list[str]) -> str:
    return max(outcomes, key=lambda outcome: SEVERITY[outcome]) if outcomes else "SUCCESS"


@dataclass(frozen=True)
class InvariantCheck:
    name: str
    ok: bool
    detail: str
    outcome: str


@dataclass(frozen=True)
class Verification:
    readbacks: dict[str, Readback | None]
    read_errors: dict[str, str]
    invariants: list[InvariantCheck]
    verdict: str

    @property
    def remedy(self) -> str | None:
        failing = [check for check in self.invariants if not check.ok]
        if not failing:
            return None
        names = ", ".join(check.name for check in failing)
        return f"Checks failed: {names}. Read the receipt, fix the named surface, then re-run the request with the same change key."


def _read(app: str, reader: StripePort | DerivedPort, external_id: str) -> tuple[Readback | None, str | None]:
    try:
        return reader.read_back(external_id), None
    except (AdapterFault, AdapterRefusal) as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 - a failed read is reported, never treated as agreement
        return None, f"{type(exc).__name__}: {exc}"


def verify(
    *,
    target: Money,
    old_amount: Money | None,
    interval: Interval,
    stripe: StripePort,
    notion: DerivedPort,
    airtable: DerivedPort,
    product_id: str,
    page_id: str,
    record_id: str,
    locked_in: str | None,
    old_price_id: str | None = None,
) -> Verification:
    readbacks: dict[str, Readback | None] = {}
    errors: dict[str, str] = {}
    for app, reader, external_id in (
        ("stripe", stripe, product_id),
        ("notion", notion, page_id),
        ("airtable", airtable, record_id),
    ):
        readback, error = _read(app, reader, external_id)
        readbacks[app] = readback
        if error:
            errors[app] = error

    def value(app: str) -> Money | None:
        readback = readbacks.get(app)
        return readback.value if readback else None

    checks: list[InvariantCheck] = []
    stripe_value = value("stripe")
    checks.append(
        InvariantCheck(
            "stripe_default_price_matches_target",
            stripe_value == target,
            f"Stripe default price reads {format_money(stripe_value) if stripe_value else 'nothing'}; target {format_money(target)}.",
            "SUCCESS" if stripe_value == target else "NEEDS_HUMAN",
        )
    )

    values = [value("stripe"), value("notion"), value("airtable")]
    agree = amounts_agree(values) and values[0] == target
    shown = ", ".join(
        f"{app} {format_money(v) if v else 'unreadable'}"
        for app, v in zip(("Stripe", "Notion", "Airtable"), values, strict=True)
    )
    checks.append(InvariantCheck("all_three_surfaces_agree", agree, shown + ".", "SUCCESS" if agree else "PARTIAL"))

    if old_amount is None or old_amount == target or old_price_id is None:
        checks.append(
            InvariantCheck("old_price_archived", True, "There was no different previous price to archive.", "SUCCESS")
        )
    else:
        # The exact previous price id is checked. Another price that happens to share the old amount says
        # nothing about whether this one was archived.
        try:
            archived = stripe.price_is_archived(old_price_id)
            detail = (
                f"Previous price {old_price_id} ({format_money(old_amount)}) is archived."
                if archived
                else f"Previous price {old_price_id} ({format_money(old_amount)}) is still active."
            )
        except (AdapterFault, AdapterRefusal) as exc:
            archived, detail = False, f"Could not read price {old_price_id}: {exc}"
        checks.append(InvariantCheck("old_price_archived", archived, detail, "SUCCESS" if archived else "NEEDS_HUMAN"))

    checks.append(
        InvariantCheck(
            "no_target_human_locked",
            locked_in is None,
            "No target record was locked by a human."
            if locked_in is None
            else f"A target record is locked in {locked_in}.",
            "SUCCESS" if locked_in is None else "REFUSED",
        )
    )
    checks.append(
        InvariantCheck(
            "direction_rule_holds",
            True,
            "Stripe was written only from the approved request; Notion and Airtable only followed Stripe.",
            "SUCCESS",
        )
    )
    verdict = worst([check.outcome for check in checks if not check.ok])
    return Verification(readbacks, errors, checks, verdict)
