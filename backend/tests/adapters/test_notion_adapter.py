"""Request shapes, Locked refusal, retries and conversion for the Notion adapter."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from pricequorum.adapters.faults import EnvFaultInjector, NoFaults
from pricequorum.adapters.notion_adapter import NOTION_VERSION, NotionAdapter
from pricequorum.ports import AdapterFault, AdapterRefusal, Money

PAGE_ID = "11111111-2222-3333-4444-555555555555"


def page(price: Any = 20, locked: bool = False, currency: str = "usd") -> dict[str, Any]:
    return {
        "object": "page",
        "id": PAGE_ID,
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Pro"}]},
            "pq_plan_id": {"type": "rich_text", "rich_text": [{"plain_text": "pro"}]},
            "Price": {"type": "number", "number": price},
            "Currency": {"type": "select", "select": {"name": currency.upper()}},
            "Interval": {"type": "select", "select": {"name": "month"}},
            "Locked": {"type": "checkbox", "checkbox": locked},
        },
    }


def build(handler: Callable[[httpx.Request], httpx.Response], faults: Any = None) -> tuple[NotionAdapter, list[float]]:
    sleeps: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return NotionAdapter("secret_unit", "ds_1", faults or NoFaults(), client=client, sleep=sleeps.append), sleeps


def test_list_plans_queries_the_data_source_and_converts_prices() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": [page(price=24.999999999999996)], "has_more": False})

    notion, _ = build(handler)
    [plan] = notion.list_plans()
    assert seen[0].method == "POST" and seen[0].url.path == "/v1/data_sources/ds_1/query"
    assert seen[0].headers["Notion-Version"] == NOTION_VERSION == "2025-09-03"
    assert plan.price == Money(2500, "usd") and plan.raw_value == "24.999999999999996"
    assert plan.pq_plan_id == "pro" and plan.label == "Pro" and plan.interval == "month"


def test_write_price_reads_locked_first_and_patches_a_json_number() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=page())

    notion, _ = build(handler)
    result = notion.write_price(PAGE_ID, Money(2500, "usd"), "pq:pro:v2:notion")
    assert result.external_object_id == PAGE_ID
    assert [r.method for r in seen] == ["GET", "PATCH"]
    assert json.loads(seen[1].content) == {"properties": {"Price": {"number": 25}}}


def test_locked_rows_are_refused_without_a_write() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=page(locked=True))

    notion, _ = build(handler)
    with pytest.raises(AdapterRefusal) as raised:
        notion.write_price(PAGE_ID, Money(2500, "usd"), "k")
    assert "Locked" in raised.value.remedy
    assert [r.method for r in seen] == ["GET"]


def test_a_different_currency_is_refused() -> None:
    notion, _ = build(lambda request: httpx.Response(200, json=page(currency="eur")))
    with pytest.raises(AdapterRefusal):
        notion.write_price(PAGE_ID, Money(2500, "usd"), "k")


def test_429_retries_honor_retry_after_then_give_up_as_a_fault() -> None:
    responses = [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json=page())]
    notion, sleeps = build(lambda request: responses.pop(0))
    assert notion.read_back(PAGE_ID).value == Money(2000, "usd")
    assert sleeps == [7.0]

    notion, sleeps = build(lambda request: httpx.Response(429))
    with pytest.raises(AdapterFault) as raised:
        notion.read_back(PAGE_ID)
    assert raised.value.kind == "rate_limit" and len(sleeps) == 3


def test_errors_map_to_faults_and_refusals_with_remedies() -> None:
    notion, _ = build(lambda request: httpx.Response(404, json={"code": "object_not_found", "message": "missing"}))
    with pytest.raises(AdapterRefusal) as refusal:
        notion.read_back(PAGE_ID)
    assert "Share the pricing database" in refusal.value.remedy

    notion, _ = build(lambda request: httpx.Response(503))
    with pytest.raises(AdapterFault) as fault:
        notion.read_back(PAGE_ID)
    assert fault.value.kind == "server_5xx"

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    notion, _ = build(timeout)
    with pytest.raises(AdapterFault) as slow:
        notion.read_back(PAGE_ID)
    assert slow.value.kind == "timeout"


def test_injected_fault_fires_after_the_patch_landed() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        return httpx.Response(200, json=page())

    notion, _ = build(handler, faults=EnvFaultInjector("half_landed"))
    with pytest.raises(AdapterFault) as raised:
        notion.write_price(PAGE_ID, Money(2500, "usd"), "k")
    assert raised.value.injected is True
    assert seen == ["GET", "PATCH"]
