"""Seeds Stripe test mode, Notion and Airtable with the three PriceQuorum demo plans. Safe to run twice.

Usage, from backend/:
    uv run python scripts/seed.py

Environment: STRIPE_SECRET_KEY, NOTION_TOKEN, NOTION_DATA_SOURCE_ID (or NOTION_PARENT_PAGE_ID to
create the database), AIRTABLE_PAT, AIRTABLE_BASE_ID, AIRTABLE_TABLE. Missing apps are skipped
with a message. Prints ids and prices only, never a secret.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import stripe

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pricequorum.adapters._http import airtable_penalty, request_json, retry_after_or_backoff  # noqa: E402
from pricequorum.adapters._money import major_json_number  # noqa: E402
from pricequorum.adapters.airtable_adapter import AIRTABLE_API, AirtableAdapter  # noqa: E402
from pricequorum.adapters.faults import NoFaults  # noqa: E402
from pricequorum.adapters.notion_adapter import NOTION_API, NOTION_VERSION, NotionAdapter  # noqa: E402
from pricequorum.adapters.stripe_adapter import StripeAdapter  # noqa: E402
from pricequorum.ports import AdapterFault, AdapterRefusal  # noqa: E402


@dataclass(frozen=True)
class SeedPlan:
    pq_plan_id: str
    name: str
    minor_units: int
    currency: str
    interval: str
    lookup_key: str


PLANS = [
    SeedPlan("pro", "Pro", 2000, "usd", "month", "pro_usd_month"),
    SeedPlan("pro_plus", "Pro Plus", 4900, "usd", "month", "pro_plus_usd_month"),
    SeedPlan("pro_eur", "Pro EUR", 1900, "eur", "month", "pro_eur_month"),
]


def env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def generic_remedy(status: int, body: dict[str, Any]) -> str:
    return "Check the credentials and ids in the environment, then run the seed again."


def seed_stripe(key: str) -> None:
    StripeAdapter(key, NoFaults())  # refuses a live key before any request
    client = stripe.StripeClient(key, max_network_retries=2)
    existing = {
        (product["metadata"] or {}).get("pq_plan_id"): product
        for product in client.v1.products.list({"active": True, "limit": 100}).data
    }
    for plan in PLANS:
        if plan.pq_plan_id in existing:
            print(f"stripe: {plan.pq_plan_id} already exists as {existing[plan.pq_plan_id]['id']}")
            continue
        product = client.v1.products.create(
            {"name": plan.name, "metadata": {"pq_plan_id": plan.pq_plan_id}},
            {"idempotency_key": f"pq-seed:{plan.pq_plan_id}:product:v1"},
        )
        price = client.v1.prices.create(
            {
                "product": product["id"],
                "unit_amount": plan.minor_units,
                "currency": plan.currency,
                "recurring": {"interval": plan.interval},  # type: ignore[typeddict-item]
                "lookup_key": plan.lookup_key,
                "transfer_lookup_key": True,
            },
            {"idempotency_key": f"pq-seed:{plan.pq_plan_id}:price:v1"},
        )
        client.v1.products.update(
            product["id"], {"default_price": price["id"]}, {"idempotency_key": f"pq-seed:{plan.pq_plan_id}:default:v1"}
        )
        amount = f"{plan.minor_units} {plan.currency}"
        print(f"stripe: created {plan.pq_plan_id} as {product['id']} with {price['id']} ({amount})")


def notion_request(client: httpx.Client, token: str, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    return request_json(
        client,
        app="notion",
        call_site=f"seed.notion.{path}",
        method=method,
        url=f"{NOTION_API}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        json=body,
        sleep=__import__("time").sleep,
        max_retries=3,
        retry_delay=retry_after_or_backoff,
        remedy_for=generic_remedy,
    )


def seed_notion(token: str, data_source_id: str | None, parent_page_id: str | None) -> None:
    client = httpx.Client(timeout=30.0)
    if not data_source_id:
        if not parent_page_id:
            print("notion: skipped, set NOTION_DATA_SOURCE_ID or NOTION_PARENT_PAGE_ID")
            return
        created = notion_request(
            client,
            token,
            "POST",
            "/databases",
            {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": "PriceQuorum pricing"}}],
                "initial_data_source": {
                    "properties": {
                        "Name": {"title": {}},
                        "pq_plan_id": {"rich_text": {}},
                        "Price": {"number": {"format": "number"}},
                        "Currency": {"select": {"options": [{"name": "usd"}, {"name": "eur"}]}},
                        "Interval": {"select": {"options": [{"name": "month"}, {"name": "year"}]}},
                        "Locked": {"checkbox": {}},
                    }
                },
            },
        )
        data_source_id = str(created["data_sources"][0]["id"])
        print(f"notion: created database {created['id']}; set NOTION_DATA_SOURCE_ID={data_source_id}")
    present = {plan.pq_plan_id for plan in NotionAdapter(token, data_source_id, NoFaults(), client=client).list_plans()}
    for plan in PLANS:
        if plan.pq_plan_id in present:
            print(f"notion: {plan.pq_plan_id} already exists")
            continue
        page = notion_request(
            client,
            token,
            "POST",
            "/pages",
            {
                "parent": {"type": "data_source_id", "data_source_id": data_source_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": plan.name}}]},
                    "pq_plan_id": {"rich_text": [{"text": {"content": plan.pq_plan_id}}]},
                    "Price": {"number": major_json_number(plan.minor_units, plan.currency)},
                    "Currency": {"select": {"name": plan.currency}},
                    "Interval": {"select": {"name": plan.interval}},
                    "Locked": {"checkbox": False},
                },
            },
        )
        print(f"notion: created {plan.pq_plan_id} as page {page['id']}")


def seed_airtable(pat: str, base_id: str, table: str) -> None:
    client = httpx.Client(timeout=30.0)
    headers = {"Authorization": f"Bearer {pat}", "Content-Type": "application/json"}

    def call(method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return request_json(
            client,
            app="airtable",
            call_site="seed.airtable",
            method=method,
            url=url,
            headers=headers,
            json=body,
            sleep=__import__("time").sleep,
            max_retries=2,
            retry_delay=airtable_penalty,
            remedy_for=generic_remedy,
        )

    tables = call("GET", f"{AIRTABLE_API}/meta/bases/{base_id}/tables").get("tables") or []
    if not any(t.get("name") == table or t.get("id") == table for t in tables):
        created = call(
            "POST",
            f"{AIRTABLE_API}/meta/bases/{base_id}/tables",
            {
                "name": table,
                "description": "PriceQuorum SKU catalogue. Follows Stripe.",
                "fields": [
                    {"name": "Name", "type": "singleLineText"},
                    {"name": "pq_plan_id", "type": "singleLineText"},
                    {"name": "Price", "type": "number", "options": {"precision": 2}},
                    {"name": "Currency", "type": "singleLineText"},
                    {"name": "Interval", "type": "singleLineText"},
                    {"name": "Locked", "type": "checkbox", "options": {"color": "redBright", "icon": "check"}},
                ],
            },
        )
        print(f"airtable: created table {created.get('id')}")
    present = {p.pq_plan_id for p in AirtableAdapter(pat, base_id, table, NoFaults(), client=client).list_plans()}
    missing = [plan for plan in PLANS if plan.pq_plan_id not in present]
    for plan in PLANS:
        if plan.pq_plan_id in present:
            print(f"airtable: {plan.pq_plan_id} already exists")
    if missing:
        created = call(
            "POST",
            f"{AIRTABLE_API}/{base_id}/{table}",
            {
                "records": [
                    {
                        "fields": {
                            "Name": plan.name,
                            "pq_plan_id": plan.pq_plan_id,
                            "Price": major_json_number(plan.minor_units, plan.currency),
                            "Currency": plan.currency,
                            "Interval": plan.interval,
                        }
                    }
                    for plan in missing
                ]
            },
        )
        for rec in created.get("records") or []:
            print(f"airtable: created {rec['fields'].get('pq_plan_id')} as {rec['id']}")


def main() -> int:
    failures = 0
    steps = [
        ("stripe", lambda: seed_stripe(key) if (key := env("STRIPE_SECRET_KEY")) else print("stripe: skipped, no key")),
        (
            "notion",
            lambda: (
                seed_notion(token, env("NOTION_DATA_SOURCE_ID"), env("NOTION_PARENT_PAGE_ID"))
                if (token := env("NOTION_TOKEN"))
                else print("notion: skipped, no NOTION_TOKEN")
            ),
        ),
        (
            "airtable",
            lambda: (
                seed_airtable(pat, base, table)
                if (pat := env("AIRTABLE_PAT"))
                and (base := env("AIRTABLE_BASE_ID"))
                and (table := env("AIRTABLE_TABLE"))
                else print("airtable: skipped, set AIRTABLE_PAT, AIRTABLE_BASE_ID and AIRTABLE_TABLE")
            ),
        ),
    ]
    for name, step in steps:
        try:
            step()
        except (AdapterRefusal, AdapterFault, stripe.StripeError, httpx.HTTPError, KeyError) as error:
            failures += 1
            remedy = getattr(error, "remedy", "")
            print(f"{name}: FAILED {error.__class__.__name__}: {str(error)[:200]} {remedy}".strip())
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
