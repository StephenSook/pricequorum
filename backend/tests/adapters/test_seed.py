"""The seed reconciles product, lookup-key price and default price independently, so a partial run is repaired."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import seed  # noqa: E402


class FakeList:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data

    def auto_paging_iter(self) -> Any:
        return iter(self.data)


class FakeStripe:
    """An in-memory Stripe with just the calls the seed makes. Records every write."""

    def __init__(self, products: list[dict[str, Any]], prices: list[dict[str, Any]]) -> None:
        self.products = products
        self.prices = prices
        self.writes: list[tuple[str, ...]] = []
        self.v1 = SimpleNamespace(
            products=SimpleNamespace(list=self.product_list, create=self.product_create, update=self.product_update),
            prices=SimpleNamespace(list=self.price_list, create=self.price_create),
        )

    def product_list(self, params: dict[str, Any]) -> FakeList:
        return FakeList([p for p in self.products if p.get("active", True)])

    def product_create(self, params: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        product = {"id": f"prod_{len(self.products)}", "active": True, "default_price": None, **params}
        self.products.append(product)
        self.writes.append(("product.create", params["metadata"]["pq_plan_id"]))
        return product

    def product_update(self, product_id: str, params: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        product = next(p for p in self.products if p["id"] == product_id)
        product.update(params)
        self.writes.append(("product.update", product_id, params["default_price"]))
        return product

    def price_list(self, params: dict[str, Any]) -> FakeList:
        keys = params.get("lookup_keys")
        return FakeList(
            [
                p
                for p in self.prices
                if (keys is None or p.get("lookup_key") in keys) and ("active" not in params or p["active"])
            ]
        )

    def price_create(self, params: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        if params.get("transfer_lookup_key"):
            for other in self.prices:
                if other.get("lookup_key") == params["lookup_key"]:
                    other["lookup_key"] = None
        price = {
            "id": f"price_{len(self.prices)}",
            "active": True,
            **{k: v for k, v in params.items() if k != "transfer_lookup_key"},
        }
        self.prices.append(price)
        self.writes.append(("price.create", params["lookup_key"]))
        return price


def test_a_product_left_without_a_price_by_a_partial_run_is_repaired() -> None:
    fake = FakeStripe(
        products=[{"id": "prod_pro", "name": "Pro", "metadata": {"pq_plan_id": "pro"}, "default_price": None}],
        prices=[],
    )
    seed.seed_stripe("sk_test_unit", client=fake)
    pro_price = next(p for p in fake.prices if p["lookup_key"] == "pro_usd_month")
    assert pro_price["product"] == "prod_pro" and pro_price["unit_amount"] == 2000
    assert ("product.update", "prod_pro", pro_price["id"]) in fake.writes
    assert ("product.create", "pro") not in fake.writes
    assert ("product.create", "pro_plus") in fake.writes and ("product.create", "pro_eur") in fake.writes

    fake.writes.clear()
    seed.seed_stripe("sk_test_unit", client=fake)
    assert fake.writes == []


def test_an_existing_price_that_is_not_the_default_only_gets_the_default_set() -> None:
    price = {
        "id": "price_pro",
        "product": "prod_pro",
        "unit_amount": 2000,
        "currency": "usd",
        "recurring": {"interval": "month"},
        "lookup_key": "pro_usd_month",
        "active": True,
    }
    fake = FakeStripe(
        products=[{"id": "prod_pro", "name": "Pro", "metadata": {"pq_plan_id": "pro"}, "default_price": None}],
        prices=[price],
    )
    seed.seed_stripe("sk_test_unit", client=fake)
    assert [w for w in fake.writes if "pro_usd_month" in w or "prod_pro" in w] == [
        ("product.update", "prod_pro", "price_pro")
    ]
