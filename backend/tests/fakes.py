"""In-memory stand-ins for Stripe, Notion, Airtable and Slack that follow pricequorum.ports.

Used only by tests. Nothing in the pricequorum package imports this module, so the running app can
never serve fake data.
"""

from __future__ import annotations

import itertools
import time
from datetime import UTC, datetime
from typing import Any

from pricequorum.adapters.faults import NoFaults
from pricequorum.money import money_from_human, to_human
from pricequorum.ports import (
    AdapterFault,
    AdapterRefusal,
    ApprovalPosted,
    ApprovalRequest,
    DecisionHandler,
    FaultInjector,
    Interval,
    Money,
    PlanRecord,
    Readback,
    WriteResult,
)

_ids = itertools.count(1)


class FakeStripe:
    app = "stripe"

    def __init__(self, faults: FaultInjector | None = None) -> None:
        self.faults: FaultInjector = faults or NoFaults()
        self.products: dict[str, dict[str, Any]] = {}
        self.prices: dict[str, dict[str, Any]] = {}
        self.keys: dict[str, str] = {}
        self.creates = 0
        self.delay = 0.0  # seconds each create takes, to hold a run inside its lock
        self.fail_next_create = False  # the next create fails before it reaches Stripe

    def _price(
        self, product_id: str, amount: Money, interval: Interval, key: str | None, lookup_key: str | None
    ) -> str:
        price_id = f"price_{next(_ids)}"
        self.prices[price_id] = {
            "product": product_id,
            "amount": amount,
            "interval": interval,
            "active": True,
            "key": key,
            "lookup_key": lookup_key,
        }
        return price_id

    def add_plan(self, pq_plan_id: str, label: str, amount: Money, interval: Interval = "month") -> str:
        product_id = f"prod_{next(_ids)}"
        price_id = self._price(product_id, amount, interval, None, None)
        self.products[product_id] = {"label": label, "pq_plan_id": pq_plan_id, "default_price": price_id}
        return product_id

    def add_price(
        self, product_id: str, amount: Money, interval: Interval = "month", idempotency_key: str | None = None
    ) -> str:
        """An active price created outside the run under test."""
        return self._price(product_id, amount, interval, idempotency_key, None)

    def list_plans(self) -> list[PlanRecord]:
        plans = []
        for product_id, product in self.products.items():
            price = self.prices[product["default_price"]]
            plans.append(
                PlanRecord(
                    app="stripe",
                    external_id=product_id,
                    pq_plan_id=product["pq_plan_id"],
                    label=product["label"],
                    price=price["amount"],
                    raw_value=str(price["amount"].minor_units),
                    interval=price["interval"],
                    locked=False,
                    price_id=product["default_price"],
                )
            )
        return plans

    def create_price(
        self, product_id: str, amount: Money, interval: Interval, lookup_key: str, idempotency_key: str
    ) -> WriteResult:
        if idempotency_key in self.keys:
            return WriteResult(self.keys[idempotency_key], replayed=True)
        if self.delay:
            time.sleep(self.delay)
        if self.fail_next_create:
            self.fail_next_create = False
            raise AdapterFault("timeout", "stripe.price.create", False, "the request never reached Stripe in this test")
        for price in self.prices.values():
            if price["lookup_key"] == lookup_key:
                price["lookup_key"] = None
        price_id = self._price(product_id, amount, interval, idempotency_key, lookup_key)
        self.keys[idempotency_key] = price_id
        self.creates += 1
        self.faults.after("stripe.price.create")
        return WriteResult(price_id)

    def set_default_price(self, product_id: str, price_id: str, idempotency_key: str) -> WriteResult:
        self.products[product_id]["default_price"] = price_id
        self.faults.after("stripe.product.update")
        return WriteResult(product_id)

    def archive_price(self, price_id: str, idempotency_key: str) -> WriteResult:
        self.prices[price_id]["active"] = False
        self.faults.after("stripe.price.update")
        return WriteResult(price_id)

    def price_is_archived(self, price_id: str) -> bool:
        return not self.prices[price_id]["active"]

    def find_created_price(
        self, product_id: str, amount: Money, interval: Interval, lookup_key: str, idempotency_key: str
    ) -> str | None:
        carrying = [price_id for price_id, price in self.prices.items() if price["key"] == idempotency_key]
        if not carrying:
            return None
        if len(carrying) > 1:
            raise AdapterRefusal("stripe", "Two prices carry one idempotency key.", "Archive the extra price.")
        price = self.prices[carrying[0]]
        if price["product"] != product_id or price["amount"] != amount or price["interval"] != interval:
            raise AdapterRefusal("stripe", "A price carries this key with other terms.", "Inspect that price.")
        if not price["active"]:
            raise AdapterRefusal("stripe", "The price created for this change is inactive.", "Recreate the price.")
        return carrying[0]

    def find_active_price(self, product_id: str, amount: Money, interval: Interval) -> str | None:
        matches = [
            pid
            for pid, p in self.prices.items()
            if p["product"] == product_id and p["active"] and p["amount"] == amount and p["interval"] == interval
        ]
        return matches[-1] if matches else None

    def active_prices(self, product_id: str) -> list[str]:
        return [pid for pid, p in self.prices.items() if p["product"] == product_id and p["active"]]

    def product_for(self, pq_plan_id: str) -> str:
        return next(pid for pid, p in self.products.items() if p["pq_plan_id"] == pq_plan_id)

    def read_back(self, product_id: str) -> Readback:
        price_id = self.products[product_id]["default_price"]
        amount = self.prices[price_id]["amount"]
        return Readback(
            app="stripe", value=amount, raw_value=str(amount.minor_units), read_at=datetime.now(UTC), source_id=price_id
        )


class FakeDerived:
    def __init__(self, app: str, faults: FaultInjector | None = None, fail_writes: bool = False) -> None:
        self.app = app
        self.faults: FaultInjector = faults or NoFaults()
        self.fail_writes = fail_writes
        self.rows: dict[str, dict[str, Any]] = {}
        self.writes = 0
        self.lock_calls: list[tuple[str, bool]] = []

    def add(
        self, pq_plan_id: str | None, label: str, human_value: float | str, currency: str, locked: bool = False
    ) -> str:
        record_id = f"{self.app}_{next(_ids)}"
        self.rows[record_id] = {
            "pq_plan_id": pq_plan_id,
            "label": label,
            "value": human_value,
            "currency": currency,
            "locked": locked,
        }
        return record_id

    def value_for(self, pq_plan_id: str) -> Any:
        return next(row["value"] for row in self.rows.values() if row["pq_plan_id"] == pq_plan_id)

    def set_locked(self, external_id: str, locked: bool) -> None:
        self.lock_calls.append((external_id, locked))
        self.rows[external_id]["locked"] = locked

    def list_plans(self) -> list[PlanRecord]:
        return [
            PlanRecord(
                app=self.app,  # type: ignore[arg-type]
                external_id=record_id,
                pq_plan_id=row["pq_plan_id"],
                label=row["label"],
                price=money_from_human(row["value"], row["currency"]),
                raw_value=str(row["value"]),
                interval=None,
                locked=row["locked"],
            )
            for record_id, row in self.rows.items()
        ]

    def write_price(self, external_id: str, amount: Money, idempotency_key: str) -> WriteResult:
        row = self.rows[external_id]
        if row["locked"]:
            raise AdapterRefusal(self.app, "The record is locked by a human.", f"Clear the Locked flag in {self.app}.")  # type: ignore[arg-type]
        if self.fail_writes:
            raise AdapterFault("server_5xx", f"{self.app}.write", False, "simulated outage in a test")
        row["value"] = float(to_human(amount.minor_units, amount.currency))
        self.writes += 1
        self.faults.after("notion.page.update" if self.app == "notion" else "airtable.upsert")
        return WriteResult(external_id)

    def read_back(self, external_id: str) -> Readback:
        row = self.rows[external_id]
        return Readback(
            app=self.app,  # type: ignore[arg-type]
            value=money_from_human(row["value"], row["currency"]),
            raw_value=str(row["value"]),
            read_at=datetime.now(UTC),
            source_id=external_id,
        )


class FakeApproval:
    def __init__(self, connected: bool = True) -> None:
        self._connected = connected
        self.posted: list[ApprovalRequest] = []
        self.outcomes: list[tuple[ApprovalPosted, str, str | None]] = []
        self.handler: DecisionHandler | None = None

    def start(self, on_decision: DecisionHandler) -> None:
        self.handler = on_decision

    def connected(self) -> bool:
        return self._connected

    def post_request(self, request: ApprovalRequest) -> ApprovalPosted:
        self.posted.append(request)
        return ApprovalPosted(channel="C0TEST", ts=f"{len(self.posted)}.000100")

    def post_outcome(self, posted: ApprovalPosted, decision: str, approver_display: str | None) -> None:
        self.outcomes.append((posted, decision, approver_display))


def world(
    stripe_faults: FaultInjector | None = None, notion_fail: bool = False, airtable_locked: bool = False
) -> tuple[FakeStripe, FakeDerived, FakeDerived]:
    stripe = FakeStripe(stripe_faults)
    stripe.add_plan("pro", "Pro", Money(2000, "usd"))
    stripe.add_plan("pro_plus", "Pro Plus", Money(4900, "usd"))
    stripe.add_plan("pro_eur", "Pro EUR", Money(1900, "eur"))
    notion = FakeDerived("notion", fail_writes=notion_fail)
    airtable = FakeDerived("airtable")
    for surface in (notion, airtable):
        surface.add("pro", "Pro", 20.0, "usd", locked=airtable_locked and surface is airtable)
        surface.add("pro_plus", "Pro Plus", 49.0, "usd")
        surface.add("pro_eur", "Pro EUR", 19.0, "eur")
    return stripe, notion, airtable


def sandbox_world() -> tuple[FakeStripe, FakeDerived, FakeDerived]:
    """The demo catalogue plus the judge sandbox plan, as scripts/seed.py is asked to create it."""
    stripe, notion, airtable = world()
    stripe.add_plan("judge_pro", "Judge Pro", Money(2000, "usd"))
    for surface in (notion, airtable):
        surface.add("judge_pro", "Judge Pro", 20.0, "usd")
    return stripe, notion, airtable
