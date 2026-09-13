"""Update shape, Locked refusal, response validation and the 30 second 429 penalty for the Airtable adapter."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from pricequorum.adapters.airtable_adapter import AirtableAdapter
from pricequorum.adapters.faults import EnvFaultInjector, NoFaults
from pricequorum.ports import AdapterFault, AdapterRefusal, Money


def record(
    price: Any = 20,
    locked: bool = False,
    pq: str | None = "pro",
    currency: str | None = "usd",
    record_id: str = "recPRO",
) -> dict[str, Any]:
    fields: dict[str, Any] = {"Name": "Pro", "Price": price, "Interval": "month"}
    if currency:
        fields["Currency"] = currency
    if pq:
        fields["pq_plan_id"] = pq
    if locked:
        fields["Locked"] = True
    return {"id": record_id, "createdTime": "2026-09-13T00:00:00.000Z", "fields": fields}


def build(
    handler: Callable[[httpx.Request], httpx.Response], faults: Any = None
) -> tuple[AirtableAdapter, list[float]]:
    sleeps: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = AirtableAdapter(
        "pat_unit", "appBASE", "Plans", faults or NoFaults(), client=client, sleep=sleeps.append, jitter=lambda: 0.5
    )
    return adapter, sleeps


def update_ok(request: httpx.Request) -> httpx.Response:
    if request.method == "GET":
        return httpx.Response(200, json=record())
    return httpx.Response(200, json=record(25))


def test_write_price_updates_the_known_record_id_and_never_uses_a_create_capable_call() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return update_ok(request)

    airtable, _ = build(handler)
    result = airtable.write_price("recPRO", Money(2500, "usd"), "pq:pro:v2:airtable")
    assert result.external_object_id == "recPRO"
    assert [r.method for r in seen] == ["GET", "PATCH"]
    assert seen[1].url.path == "/v0/appBASE/Plans/recPRO"
    body = json.loads(seen[1].content)
    assert body == {"fields": {"Price": 25}, "typecast": False}


def test_a_record_deleted_after_the_read_fails_instead_of_creating_a_new_one() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.method == "GET":
            return httpx.Response(200, json=record())
        return httpx.Response(404, json={"error": "NOT_FOUND"})

    airtable, _ = build(handler)
    with pytest.raises(AdapterRefusal):
        airtable.write_price("recPRO", Money(2500, "usd"), "k")
    assert seen == ["GET /v0/appBASE/Plans/recPRO", "PATCH /v0/appBASE/Plans/recPRO"]


def test_locked_unkeyed_and_currencyless_records_are_refused_without_a_write() -> None:
    cases = ((record(locked=True), "Locked"), (record(pq=None), "pq_plan_id"), (record(currency=None), "Currency"))
    for payload, remedy in cases:
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


def test_malformed_or_foreign_success_bodies_are_faults_and_nothing_is_written() -> None:
    bodies = [
        httpx.Response(200, text="<html>maintenance</html>", headers={"content-type": "text/html"}),
        httpx.Response(200, json=record(record_id="recOTHER")),
        httpx.Response(200, json={"id": "recPRO", "fields": "not an object"}),
        httpx.Response(301, headers={"location": "https://example.com"}),
    ]
    for response in bodies:
        seen: list[str] = []

        def handler(
            request: httpx.Request, response: httpx.Response = response, seen: list[str] = seen
        ) -> httpx.Response:
            seen.append(request.method)
            return response

        airtable, _ = build(handler)
        with pytest.raises(AdapterFault) as raised:
            airtable.write_price("recPRO", Money(2500, "usd"), "k")
        assert raised.value.kind == "server_5xx"
        assert seen == ["GET"]


def test_a_write_response_for_a_different_record_is_a_fault() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=record())
        return httpx.Response(200, json=record(25, record_id="recOTHER"))

    airtable, _ = build(handler)
    with pytest.raises(AdapterFault):
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


def test_list_plans_follows_offsets_and_injected_fault_fires_after_the_update() -> None:
    pages = [{"records": [record()], "offset": "next"}, {"records": [record(pq="pro_plus")]}]
    airtable, _ = build(lambda request: httpx.Response(200, json=pages.pop(0)))
    plans = airtable.list_plans()
    assert [p.pq_plan_id for p in plans] == ["pro", "pro_plus"]

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        return update_ok(request)

    airtable, _ = build(handler, faults=EnvFaultInjector("rate_limit_429"))
    with pytest.raises(AdapterFault) as raised:
        airtable.write_price("recPRO", Money(2500, "usd"), "k")
    assert raised.value.injected is True and seen == ["GET", "PATCH"]


def test_auth_errors_carry_a_token_remedy() -> None:
    airtable, _ = build(lambda request: httpx.Response(401, json={"error": {"type": "AUTHENTICATION_REQUIRED"}}))
    with pytest.raises(AdapterRefusal) as raised:
        airtable.read_back("recPRO")
    assert "AIRTABLE_PAT" in raised.value.remedy
