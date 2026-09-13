"""Upsert shape, Locked refusal and the 30 second 429 penalty for the Airtable adapter."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from pricequorum.adapters.airtable_adapter import AirtableAdapter
from pricequorum.adapters.faults import EnvFaultInjector, NoFaults
from pricequorum.ports import AdapterFault, AdapterRefusal, Money


def record(price: Any = 20, locked: bool = False, pq: str | None = "pro") -> dict[str, Any]:
    fields: dict[str, Any] = {"Name": "Pro", "Price": price, "Currency": "usd", "Interval": "month"}
    if pq:
        fields["pq_plan_id"] = pq
    if locked:
        fields["Locked"] = True
    return {"id": "recPRO", "createdTime": "2026-09-13T00:00:00.000Z", "fields": fields}


def build(
    handler: Callable[[httpx.Request], httpx.Response], faults: Any = None
) -> tuple[AirtableAdapter, list[float]]:
    sleeps: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = AirtableAdapter(
        "pat_unit", "appBASE", "Plans", faults or NoFaults(), client=client, sleep=sleeps.append, jitter=lambda: 0.5
    )
    return adapter, sleeps


def upsert_ok(request: httpx.Request) -> httpx.Response:
    if request.method == "GET":
        return httpx.Response(200, json=record())
    return httpx.Response(200, json={"records": [record(25)], "updatedRecords": ["recPRO"], "createdRecords": []})


def test_write_price_upserts_on_pq_plan_id_with_a_json_number() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return upsert_ok(request)

    airtable, _ = build(handler)
    result = airtable.write_price("recPRO", Money(2500, "usd"), "pq:pro:v2:airtable")
    assert result.external_object_id == "recPRO"
    assert [r.method for r in seen] == ["GET", "PATCH"]
    assert seen[1].url.path == "/v0/appBASE/Plans"
    body = json.loads(seen[1].content)
    assert body == {
        "performUpsert": {"fieldsToMergeOn": ["pq_plan_id"]},
        "records": [{"fields": {"pq_plan_id": "pro", "Price": 25}}],
    }


def test_locked_and_unkeyed_records_are_refused_without_a_write() -> None:
    for payload, remedy in ((record(locked=True), "Locked"), (record(pq=None), "pq_plan_id")):
        seen: list[str] = []

        def handler(
            request: httpx.Request, payload: dict[str, Any] = payload, seen: list[str] = seen
        ) -> httpx.Response:
            seen.append(request.method)
            return httpx.Response(200, json=payload)

        airtable, _ = build(handler)
        with pytest.raises(AdapterRefusal) as raised:
            airtable.write_price("recPRO", Money(2500, "usd"), "k")
        assert remedy in raised.value.remedy
        assert seen == ["GET"]


def test_an_upsert_that_creates_a_record_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=record())
        return httpx.Response(200, json={"records": [record()], "updatedRecords": [], "createdRecords": ["recNEW"]})

    airtable, _ = build(handler)
    with pytest.raises(AdapterRefusal):
        airtable.write_price("recPRO", Money(2500, "usd"), "k")


def test_429_waits_thirty_seconds_with_jitter_then_becomes_a_fault() -> None:
    responses = [httpx.Response(429), httpx.Response(200, json=record())]
    airtable, sleeps = build(lambda request: responses.pop(0))
    assert airtable.read_back("recPRO").value == Money(2000, "usd")
    assert sleeps == [31.5]

    airtable, sleeps = build(lambda request: httpx.Response(429))
    with pytest.raises(AdapterFault) as raised:
        airtable.read_back("recPRO")
    assert raised.value.kind == "rate_limit" and sleeps == [31.5, 31.5]


def test_list_plans_follows_offsets_and_injected_fault_fires_after_the_upsert() -> None:
    pages = [{"records": [record()], "offset": "next"}, {"records": [record(pq="pro_plus")]}]
    airtable, _ = build(lambda request: httpx.Response(200, json=pages.pop(0)))
    plans = airtable.list_plans()
    assert [p.pq_plan_id for p in plans] == ["pro", "pro_plus"]

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        return upsert_ok(request)

    airtable, _ = build(handler, faults=EnvFaultInjector("rate_limit_429"))
    with pytest.raises(AdapterFault) as raised:
        airtable.write_price("recPRO", Money(2500, "usd"), "k")
    assert raised.value.injected is True and seen == ["GET", "PATCH"]


def test_auth_errors_carry_a_token_remedy() -> None:
    airtable, _ = build(lambda request: httpx.Response(401, json={"error": {"type": "AUTHENTICATION_REQUIRED"}}))
    with pytest.raises(AdapterRefusal) as raised:
        airtable.read_back("recPRO")
    assert "AIRTABLE_PAT" in raised.value.remedy
