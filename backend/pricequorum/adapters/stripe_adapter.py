"""Stripe, the authoritative billing system. Test mode only.

A Stripe Price amount cannot be edited, so a price change is a migration: create a new price
that takes over the lookup key, make it the product's default, then archive the old price.
Every write carries an Idempotency-Key so a retry after a timeout never creates a second price.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

import stripe

from pricequorum.ports import (
    AdapterFault,
    AdapterRefusal,
    FaultInjector,
    Interval,
    Money,
    PlanRecord,
    Readback,
    WriteResult,
)

T = TypeVar("T")

_INTERVALS: tuple[Interval, ...] = ("month", "year")


def _get(obj: Any, key: str) -> Any:
    """Reads a field from a StripeObject, a plain dict, or None."""
    if obj is None:
        return None
    try:
        return obj[key]
    except (KeyError, TypeError):
        return getattr(obj, key, None)


def _message(error: stripe.StripeError) -> str:
    return (error.user_message or str(error) or error.__class__.__name__)[:300]


class StripeAdapter:
    app = "stripe"

    def __init__(self, secret_key: str, faults: FaultInjector, client: stripe.StripeClient | None = None) -> None:
        if secret_key.startswith(("sk_live_", "rk_live_")):
            raise AdapterRefusal(
                "stripe",
                "A live Stripe key was supplied, and PriceQuorum only runs against Stripe test mode.",
                "Set STRIPE_SECRET_KEY to a test mode key that starts with sk_test_.",
            )
        if not secret_key.startswith(("sk_test_", "rk_test_")):
            raise AdapterRefusal(
                "stripe",
                "STRIPE_SECRET_KEY is not a Stripe test mode secret key.",
                "Copy the test mode secret key from the Stripe dashboard (Developers, API keys).",
            )
        self._faults = faults
        # No hidden retries: after a failure the orchestrator reads Stripe back before retrying.
        self._client = client or stripe.StripeClient(secret_key, max_network_retries=0)

    def _call(self, call_site: str, fn: Callable[[], T]) -> T:
        try:
            return fn()
        except stripe.IdempotencyError as error:
            raise AdapterFault("conflict_409", call_site, False, _message(error)) from error
        except stripe.RateLimitError as error:
            raise AdapterFault("rate_limit", call_site, False, _message(error)) from error
        except stripe.APIConnectionError as error:
            raise AdapterFault("timeout", call_site, False, _message(error)) from error
        except stripe.AuthenticationError as error:
            raise AdapterRefusal(
                "stripe", f"Stripe rejected the API key: {_message(error)}", "Check STRIPE_SECRET_KEY."
            ) from error
        except stripe.StripeError as error:
            status = error.http_status or 0
            if status == 409:
                raise AdapterFault("conflict_409", call_site, False, _message(error)) from error
            if status == 429:
                raise AdapterFault("rate_limit", call_site, False, _message(error)) from error
            if status >= 500 or isinstance(error, stripe.APIError):
                raise AdapterFault("server_5xx", call_site, False, _message(error)) from error
            raise AdapterRefusal(
                "stripe",
                f"Stripe refused {call_site}: {_message(error)}",
                "Check the Stripe product and price in test mode match the plan being changed.",
            ) from error

    @staticmethod
    def _replayed(obj: Any) -> bool:
        response = getattr(obj, "last_response", None)
        headers = getattr(response, "headers", None) or {}
        try:
            return str(headers.get("Idempotent-Replayed", "")).lower() == "true"
        except AttributeError:
            return False

    @staticmethod
    def _money(price: Any) -> Money | None:
        amount = _get(price, "unit_amount")
        currency = _get(price, "currency")
        if isinstance(amount, int) and not isinstance(amount, bool) and isinstance(currency, str):
            try:
                return Money(amount, currency.lower())
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _interval(price: Any) -> Interval | None:
        interval = _get(_get(price, "recurring"), "interval")
        return interval if interval in _INTERVALS else None

    def _retrieve_price(self, price_id: str) -> Any:
        return self._call("stripe.price.retrieve", lambda: self._client.v1.prices.retrieve(price_id))

    def list_plans(self) -> list[PlanRecord]:
        products = self._call(
            "stripe.product.list",
            lambda: self._client.v1.products.list({"active": True, "limit": 100, "expand": ["data.default_price"]}),
        )
        plans: list[PlanRecord] = []
        for product in _get(products, "data") or []:
            price = _get(product, "default_price")
            if isinstance(price, str):  # not expanded; fetch it so the amount is real
                price = self._retrieve_price(price)
            amount = _get(price, "unit_amount")
            metadata = _get(product, "metadata") or {}
            plans.append(
                PlanRecord(
                    app="stripe",
                    external_id=str(_get(product, "id")),
                    pq_plan_id=_get(metadata, "pq_plan_id") or None,
                    label=str(_get(product, "name") or ""),
                    price=self._money(price),
                    raw_value=None if amount is None else str(amount),
                    interval=self._interval(price),
                    locked=False,
                    price_id=_get(price, "id"),
                )
            )
        return plans

    def create_price(
        self, product_id: str, amount: Money, interval: Interval, lookup_key: str, idempotency_key: str
    ) -> WriteResult:
        params = {
            "product": product_id,
            "unit_amount": amount.minor_units,
            "currency": amount.currency,
            "recurring": {"interval": interval},
            "lookup_key": lookup_key,
            "transfer_lookup_key": True,
            "metadata": {"pq_idempotency_key": idempotency_key},
        }
        price = self._call(
            "stripe.price.create",
            lambda: self._client.v1.prices.create(params, {"idempotency_key": idempotency_key}),  # type: ignore[arg-type]
        )
        self._faults.after("stripe.price.create")
        return WriteResult(external_object_id=str(_get(price, "id")), replayed=self._replayed(price))

    def set_default_price(self, product_id: str, price_id: str, idempotency_key: str) -> WriteResult:
        product = self._call(
            "stripe.product.update",
            lambda: self._client.v1.products.update(
                product_id, {"default_price": price_id}, {"idempotency_key": idempotency_key}
            ),
        )
        self._faults.after("stripe.product.update")
        return WriteResult(external_object_id=str(_get(product, "id")), replayed=self._replayed(product))

    def archive_price(self, price_id: str, idempotency_key: str) -> WriteResult:
        price = self._call(
            "stripe.price.update",
            lambda: self._client.v1.prices.update(price_id, {"active": False}, {"idempotency_key": idempotency_key}),
        )
        self._faults.after("stripe.price.update")
        return WriteResult(external_object_id=str(_get(price, "id")), replayed=self._replayed(price))

    def find_active_price(self, product_id: str, amount: Money, interval: Interval) -> str | None:
        prices = self._call(
            "stripe.price.list",
            lambda: self._client.v1.prices.list({"product": product_id, "active": True, "limit": 100}),
        )
        matches = [
            price
            for price in _get(prices, "data") or []
            if self._money(price) == amount and self._interval(price) == interval
        ]
        if not matches:
            return None
        newest = max(matches, key=lambda price: _get(price, "created") or 0)
        return str(_get(newest, "id"))

    def read_back(self, product_id: str) -> Readback:
        product = self._call(
            "stripe.product.retrieve",
            lambda: self._client.v1.products.retrieve(product_id, {"expand": ["default_price"]}),
        )
        price = _get(product, "default_price")
        if isinstance(price, str):
            price_id = price
            price = self._call("stripe.price.retrieve", lambda: self._client.v1.prices.retrieve(price_id))
        amount = _get(price, "unit_amount")
        return Readback(
            app="stripe",
            value=self._money(price),
            raw_value=None if amount is None else str(amount),
            read_at=datetime.now(UTC),
            source_id=str(_get(price, "id") or product_id),
        )
