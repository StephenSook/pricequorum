"""Returns the three demo plans to their seed prices in Stripe, Notion and Airtable, and unlocks them.

Stripe prices are archived, never deleted (a product with prices cannot be deleted). Run from
backend/ with the same environment as scripts/seed.py. Prints ids and prices only.
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import stripe

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from seed import PLANS, env, generic_remedy, notion_request  # noqa: E402

from pricequorum.adapters._http import airtable_penalty, request_json  # noqa: E402
from pricequorum.adapters._money import major_json_number  # noqa: E402
from pricequorum.adapters.airtable_adapter import AIRTABLE_API, AirtableAdapter  # noqa: E402
from pricequorum.adapters.faults import NoFaults  # noqa: E402
from pricequorum.adapters.notion_adapter import NotionAdapter  # noqa: E402
from pricequorum.adapters.stripe_adapter import StripeAdapter  # noqa: E402
from pricequorum.ports import AdapterFault, AdapterRefusal, Money  # noqa: E402


def reset_stripe(key: str) -> None:
    adapter = StripeAdapter(key, NoFaults())
    client = stripe.StripeClient(key, max_network_retries=2)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    by_plan = {plan.pq_plan_id: plan for plan in adapter.list_plans() if plan.pq_plan_id}
    for seed in PLANS:
        record = by_plan.get(seed.pq_plan_id)
        if record is None:
            print(f"stripe: {seed.pq_plan_id} not found, run scripts/seed.py")
            continue
        target = Money(seed.minor_units, seed.currency)
        default_id = record.price_id
        if record.price != target:
            default_id = (
                adapter.find_active_price(record.external_id, target, "month")
                or adapter.create_price(
                    record.external_id, target, "month", seed.lookup_key, f"pq-reset:{seed.pq_plan_id}:{stamp}"
                ).external_object_id
            )
            adapter.set_default_price(record.external_id, default_id, f"pq-reset:{seed.pq_plan_id}:default:{stamp}")
        archived = 0
        for price in client.v1.prices.list({"product": record.external_id, "active": True, "limit": 100}).data:
            if price["id"] != default_id:
                adapter.archive_price(price["id"], f"pq-reset:{price['id']}:archive:{stamp}")
                archived += 1
        print(
            f"stripe: {seed.pq_plan_id} default {default_id} at {seed.minor_units} {seed.currency}, archived {archived}"
        )


def reset_notion(token: str, data_source_id: str) -> None:
    client = httpx.Client(timeout=30.0)
    rows = {p.pq_plan_id: p for p in NotionAdapter(token, data_source_id, NoFaults(), client=client).list_plans()}
    for seed in PLANS:
        row = rows.get(seed.pq_plan_id)
        if row is None:
            print(f"notion: {seed.pq_plan_id} not found, run scripts/seed.py")
            continue
        notion_request(
            client,
            token,
            "PATCH",
            f"/pages/{row.external_id}",
            {
                "properties": {
                    "Price": {"number": major_json_number(seed.minor_units, seed.currency)},
                    "Locked": {"checkbox": False},
                }
            },
        )
        print(f"notion: {seed.pq_plan_id} reset to {seed.minor_units} {seed.currency} and unlocked")


def reset_airtable(pat: str, base_id: str, table: str) -> None:
    client = httpx.Client(timeout=30.0)
    present = {p.pq_plan_id for p in AirtableAdapter(pat, base_id, table, NoFaults(), client=client).list_plans()}
    records: list[dict[str, Any]] = [
        {
            "fields": {
                "pq_plan_id": seed.pq_plan_id,
                "Price": major_json_number(seed.minor_units, seed.currency),
                "Locked": False,
            }
        }
        for seed in PLANS
        if seed.pq_plan_id in present
    ]
    if not records:
        print("airtable: no seeded records found, run scripts/seed.py")
        return
    request_json(
        client,
        app="airtable",
        call_site="reset.airtable",
        method="PATCH",
        url=f"{AIRTABLE_API}/{base_id}/{table}",
        headers={"Authorization": f"Bearer {pat}", "Content-Type": "application/json"},
        json={"performUpsert": {"fieldsToMergeOn": ["pq_plan_id"]}, "records": records},
        sleep=time.sleep,
        max_retries=2,
        retry_delay=airtable_penalty,
        remedy_for=generic_remedy,
    )
    print(f"airtable: reset {len(records)} records to seed prices and unlocked")


def main() -> int:
    failures = 0
    steps = []
    if key := env("STRIPE_SECRET_KEY"):
        steps.append(("stripe", lambda: reset_stripe(key)))
    if (token := env("NOTION_TOKEN")) and (ds := env("NOTION_DATA_SOURCE_ID")):
        steps.append(("notion", lambda: reset_notion(token, ds)))
    if (pat := env("AIRTABLE_PAT")) and (base := env("AIRTABLE_BASE_ID")) and (table := env("AIRTABLE_TABLE")):
        steps.append(("airtable", lambda: reset_airtable(pat, base, table)))
    if not steps:
        print("reset: nothing configured")
        return 1
    for name, step in steps:
        try:
            step()
        except (AdapterRefusal, AdapterFault, stripe.StripeError, httpx.HTTPError) as error:
            failures += 1
            print(
                f"{name}: FAILED {error.__class__.__name__}: {str(error)[:200]} {getattr(error, 'remedy', '')}".strip()
            )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
