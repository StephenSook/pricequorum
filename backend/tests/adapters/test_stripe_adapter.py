"""Request shapes and error mapping for the Stripe adapter, against a recording HTTP client."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import stripe

from pricequorum.adapters.faults import EnvFaultInjector, NoFaults
from pricequorum.adapters.stripe_adapter import StripeAdapter
from pricequorum.ports import AdapterFault, AdapterRefusal, Money

PRICE = {
    "id": "price_new",
    "object": "price",
    "unit_amount": 2500,
    "currency": "usd",
    "recurring": {"interval": "month"},
    "created": 2,
}


class RecordingClient(stripe.HTTPClient):
    name = "recording"

    def __init__(self, responses: list[tuple[int, dict[str, Any]] | Exception]) -> None:
        super().__init__()
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, headers: Any, post_data: Any = None, *, _usage: Any = None) -> Any:
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "body": post_data})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, body = response
        return json.dumps(body), status, {"Request-Id": "req_test"}

    def request_stream(self, method: str, url: str, headers: Any, post_data: Any = None, *, _usage: Any = None) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        return None


def adapter(
    responses: list[tuple[int, dict[str, Any]] | Exception], faults: Any = None
) -> tuple[StripeAdapter, RecordingClient]:
    http = RecordingClient(responses)
    client = stripe.StripeClient("sk_test_unit", http_client=http, max_network_retries=0)
    return StripeAdapter("sk_test_unit", faults or NoFaults(), client=client), http


def form(call: dict[str, Any]) -> dict[str, list[str]]:
    body = call["body"] or ""
    return parse_qs(body.decode() if isinstance(body, bytes) else body)


def test_live_keys_are_refused_before_any_request() -> None:
    with pytest.raises(AdapterRefusal) as raised:
        StripeAdapter("sk_live_nope", NoFaults())
    assert "test mode" in raised.value.remedy
    with pytest.raises(AdapterRefusal):
        StripeAdapter("pk_test_publishable", NoFaults())


def test_create_price_transfers_the_lookup_key_with_an_idempotency_key() -> None:
    stripe_adapter, http = adapter([(200, PRICE)])
    result = stripe_adapter.create_price(
        "prod_1", Money(2500, "usd"), "month", "pro_usd_month", "pq:pro:v2:create_price"
    )
    assert result.external_object_id == "price_new"
    call = http.calls[0]
    assert call["method"] == "post" and urlparse(call["url"]).path == "/v1/prices"
    assert call["headers"]["Idempotency-Key"] == "pq:pro:v2:create_price"
    body = form(call)
    assert body["lookup_key"] == ["pro_usd_month"]
    assert body["transfer_lookup_key"] == ["true"]
    assert body["unit_amount"] == ["2500"] and body["currency"] == ["usd"]
    assert body["recurring[interval]"] == ["month"]


def test_injected_fault_fires_after_the_real_request_was_sent() -> None:
    stripe_adapter, http = adapter([(200, PRICE)], faults=EnvFaultInjector("timeout_after_commit"))
    with pytest.raises(AdapterFault) as raised:
        stripe_adapter.create_price("prod_1", Money(2500, "usd"), "month", "pro_usd_month", "k1")
    assert raised.value.injected is True and raised.value.call_site == "stripe.price.create"
    assert len(http.calls) == 1


@pytest.mark.parametrize(
    ("status", "error", "kind"),
    [
        (429, {"type": "invalid_request_error", "code": "rate_limit", "message": "slow down"}, "rate_limit"),
        (409, {"type": "idempotency_error", "message": "key in use"}, "conflict_409"),
        (500, {"type": "api_error", "message": "boom"}, "server_5xx"),
    ],
)
def test_transport_errors_become_faults(status: int, error: dict[str, Any], kind: str) -> None:
    stripe_adapter, _ = adapter([(status, {"error": error})])
    with pytest.raises(AdapterFault) as raised:
        stripe_adapter.archive_price("price_old", "k2")
    assert raised.value.kind == kind and raised.value.injected is False


def test_connection_errors_become_timeouts_and_invalid_requests_become_refusals() -> None:
    stripe_adapter, _ = adapter([stripe.APIConnectionError("read timed out")])
    with pytest.raises(AdapterFault) as fault:
        stripe_adapter.set_default_price("prod_1", "price_new", "k3")
    assert fault.value.kind == "timeout"

    stripe_adapter, _ = adapter([(400, {"error": {"type": "invalid_request_error", "message": "No such product"}})])
    with pytest.raises(AdapterRefusal) as refusal:
        stripe_adapter.set_default_price("prod_missing", "price_new", "k4")
    assert "No such product" in refusal.value.reason


def test_list_plans_and_read_back_use_real_amounts() -> None:
    product = {
        "id": "prod_1",
        "object": "product",
        "name": "Pro",
        "metadata": {"pq_plan_id": "pro"},
        "default_price": {**PRICE, "id": "price_old", "unit_amount": 2000},
    }
    stripe_adapter, http = adapter(
        [(200, {"object": "list", "data": [product], "has_more": False, "url": "/v1/products"})]
    )
    [plan] = stripe_adapter.list_plans()
    assert plan.pq_plan_id == "pro" and plan.price == Money(2000, "usd") and plan.price_id == "price_old"
    assert plan.interval == "month" and plan.locked is False
    assert "expand[0]=data.default_price" in http.calls[0]["url"].replace("%5B", "[").replace("%5D", "]")

    stripe_adapter, _ = adapter([(200, {**product, "default_price": PRICE})])
    readback = stripe_adapter.read_back("prod_1")
    assert readback.value == Money(2500, "usd") and readback.source_id == "price_new"
    assert readback.read_at.tzinfo is not None


def listing(data: list[dict[str, Any]], has_more: bool = False) -> dict[str, Any]:
    return {"object": "list", "data": data, "has_more": has_more, "url": "/v1/prices"}


CREATED = {
    **PRICE,
    "product": "prod_1",
    "lookup_key": "pro_usd_month",
    "active": True,
    "metadata": {"pq_idempotency_key": "pq:pro:v2:create_price"},
}


def test_find_active_price_follows_pagination() -> None:
    other = {**PRICE, "id": "price_other", "unit_amount": 1900}
    stripe_adapter, http = adapter([(200, listing([other], has_more=True)), (200, listing([PRICE]))])
    assert stripe_adapter.find_active_price("prod_1", Money(2500, "usd"), "month") == "price_new"
    assert len(http.calls) == 2 and "starting_after=price_other" in http.calls[1]["url"]


def test_find_created_price_recovers_by_lookup_key_and_idempotency_metadata() -> None:
    stripe_adapter, http = adapter([(200, listing([CREATED]))])
    found = stripe_adapter.find_created_price(
        "prod_1", Money(2500, "usd"), "month", "pro_usd_month", "pq:pro:v2:create_price"
    )
    assert found == "price_new"
    assert "lookup_keys" in http.calls[0]["url"]


def test_find_created_price_ignores_prices_without_our_key_and_scans_every_page() -> None:
    impostor = {**CREATED, "id": "price_impostor", "metadata": {}}
    moved = {**CREATED, "lookup_key": "pro_usd_month_v3"}  # the lookup key was transferred away later
    stripe_adapter, http = adapter(
        [(200, listing([impostor])), (200, listing([impostor], has_more=True)), (200, listing([moved]))]
    )
    found = stripe_adapter.find_created_price(
        "prod_1", Money(2500, "usd"), "month", "pro_usd_month", "pq:pro:v2:create_price"
    )
    assert found == "price_new" and len(http.calls) == 3


def test_find_created_price_is_none_when_nothing_carries_our_key() -> None:
    stripe_adapter, _ = adapter([(200, listing([])), (200, listing([{**CREATED, "metadata": {}}]))])
    assert stripe_adapter.find_created_price("prod_1", Money(2500, "usd"), "month", "pro_usd_month", "k9") is None


def test_find_created_price_refuses_our_key_on_a_price_with_other_terms() -> None:
    wrong = {**CREATED, "unit_amount": 2400}
    stripe_adapter, _ = adapter([(200, listing([wrong]))])
    with pytest.raises(AdapterRefusal):
        stripe_adapter.find_created_price(
            "prod_1", Money(2500, "usd"), "month", "pro_usd_month", "pq:pro:v2:create_price"
        )


def test_price_is_archived_reads_the_exact_price_id() -> None:
    stripe_adapter, http = adapter([(200, {**PRICE, "id": "price_old", "active": False})])
    assert stripe_adapter.price_is_archived("price_old") is True
    assert urlparse(http.calls[0]["url"]).path == "/v1/prices/price_old"
    stripe_adapter, _ = adapter([(200, {**PRICE, "id": "price_old", "active": True})])
    assert stripe_adapter.price_is_archived("price_old") is False
    stripe_adapter, _ = adapter([(200, {**PRICE, "id": "price_old"})])
    with pytest.raises(AdapterFault):
        stripe_adapter.price_is_archived("price_old")


def test_archive_price_rejects_a_response_that_is_still_active() -> None:
    stripe_adapter, _ = adapter([(200, {**PRICE, "id": "price_old", "active": True})])
    with pytest.raises(AdapterFault):
        stripe_adapter.archive_price("price_old", "k")


def test_find_active_price_matches_amount_and_interval() -> None:
    yearly = {**PRICE, "id": "price_year", "recurring": {"interval": "year"}}
    other = {**PRICE, "id": "price_other", "unit_amount": 1900}
    stripe_adapter, _ = adapter(
        [(200, {"object": "list", "data": [yearly, other, PRICE], "has_more": False, "url": "/v1/prices"})]
    )
    assert stripe_adapter.find_active_price("prod_1", Money(2500, "usd"), "month") == "price_new"
    stripe_adapter, _ = adapter([(200, {"object": "list", "data": [other], "has_more": False, "url": "/v1/prices"})])
    assert stripe_adapter.find_active_price("prod_1", Money(2500, "usd"), "month") is None
