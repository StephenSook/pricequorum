"""Notion, the derived public pricing page. Follows Stripe, never the other way.

Uses API version 2025-09-03, where a database's rows live in a data source. Rows are located by
their stored page id, never by title. Before every write the page is read and validated: it must
be the page that was asked for, and it must carry a readable Locked checkbox and a Currency, or
nothing is written.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx

from pricequorum.adapters._http import Sleep, request_json, retry_after_or_backoff
from pricequorum.adapters._money import major_json_number, major_to_minor
from pricequorum.ports import (
    AdapterFault,
    AdapterRefusal,
    AppName,
    FaultInjector,
    Interval,
    Money,
    PlanRecord,
    Readback,
    WriteResult,
)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
_INTERVALS: tuple[Interval, ...] = ("month", "year")
_SCHEMA_REMEDY = "Check the data source has the properties Name, pq_plan_id, Price, Currency, Interval and Locked."


def _remedy(status: int, body: dict[str, Any]) -> str:
    code = body.get("code")
    if code == "object_not_found" or status == 404:
        return "Share the pricing database with the PriceQuorum integration in Notion (the page menu, Connections)."
    if code in ("unauthorized", "restricted_resource") or status in (401, 403):
        return "Check NOTION_TOKEN and that the integration has read, update and insert content capabilities."
    if code == "validation_error":
        return _SCHEMA_REMEDY
    return "Check the Notion data source configuration and try again."


def _text(prop: dict[str, Any] | None) -> str | None:
    if not isinstance(prop, dict):
        return None
    items = prop.get("title") or prop.get("rich_text") or []
    if not isinstance(items, list):
        return None
    value = "".join(str(item.get("plain_text", "")) for item in items if isinstance(item, dict))
    return value or None


def _select(prop: dict[str, Any] | None) -> str | None:
    option = prop.get("select") if isinstance(prop, dict) else None
    return str(option["name"]) if isinstance(option, dict) and option.get("name") else None


def _compact(page_id: str) -> str:
    return page_id.replace("-", "").lower()


def _page_properties(body: dict[str, Any], call_site: str, expected_id: str | None) -> dict[str, Any]:
    """Checks the body is a page (and the requested one). A malformed success body is a fault."""
    properties = body.get("properties")
    page_id = body.get("id")
    if body.get("object") != "page" or not isinstance(properties, dict) or not isinstance(page_id, str):
        raise AdapterFault("server_5xx", call_site, False, "Notion answered without a readable page object")
    if expected_id is not None and _compact(page_id) != _compact(expected_id):
        raise AdapterFault(
            "server_5xx", call_site, False, "Notion answered with a different page than the one requested"
        )
    return properties


class NotionAdapter:
    app: AppName = "notion"

    def __init__(
        self,
        token: str,
        data_source_id: str,
        faults: FaultInjector,
        client: httpx.Client | None = None,
        sleep: Sleep = time.sleep,
        max_retries: int = 3,
    ) -> None:
        self._data_source_id = data_source_id
        self._faults = faults
        self._client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
        self._sleep = sleep
        self._max_retries = max_retries
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _request(self, call_site: str, method: str, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        return request_json(
            self._client,
            app="notion",
            call_site=call_site,
            method=method,
            url=f"{NOTION_API}{path}",
            headers=self._headers,
            json=json,
            sleep=self._sleep,
            max_retries=self._max_retries,
            retry_delay=retry_after_or_backoff,
            remedy_for=_remedy,
        )

    @staticmethod
    def _parse(page_id: str, props: dict[str, Any]) -> PlanRecord:
        currency_name = _select(props.get("Currency"))
        currency = currency_name.lower() if currency_name else None
        price_prop = props.get("Price")
        number = price_prop.get("number") if isinstance(price_prop, dict) else None
        price: Money | None = None
        if currency is not None:
            minor = major_to_minor(number, currency)
            if minor is not None:
                try:
                    price = Money(minor, currency)
                except ValueError:
                    price = None
        interval = _select(props.get("Interval"))
        locked_prop = props.get("Locked")
        return PlanRecord(
            app="notion",
            external_id=page_id,
            pq_plan_id=_text(props.get("pq_plan_id")),
            label=_text(props.get("Name")) or "",
            price=price,
            raw_value=None if number is None else str(number),
            interval=interval if interval in _INTERVALS else None,  # type: ignore[arg-type]
            locked=bool(locked_prop.get("checkbox", False)) if isinstance(locked_prop, dict) else False,
        )

    def list_plans(self) -> list[PlanRecord]:
        plans: list[PlanRecord] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            call_site = "notion.data_source.query"
            page = self._request(call_site, "POST", f"/data_sources/{self._data_source_id}/query", body)
            results = page.get("results")
            if not isinstance(results, list):
                raise AdapterFault("server_5xx", call_site, False, "Notion answered a query without a results list")
            for item in results:
                if isinstance(item, dict) and item.get("object") == "page":
                    plans.append(self._parse(str(item.get("id")), _page_properties(item, call_site, None)))
            if not page.get("has_more") or not page.get("next_cursor"):
                return plans
            cursor = str(page["next_cursor"])

    def _fetch(self, page_id: str) -> tuple[PlanRecord, dict[str, Any]]:
        call_site = "notion.page.retrieve"
        props = _page_properties(self._request(call_site, "GET", f"/pages/{page_id}"), call_site, page_id)
        return self._parse(page_id, props), props

    def write_price(self, external_id: str, amount: Money, idempotency_key: str) -> WriteResult:
        # Notion has no idempotency keys; setting an absolute value is naturally idempotent.
        current, props = self._fetch(external_id)
        locked_prop = props.get("Locked")
        if not isinstance(locked_prop, dict) or not isinstance(locked_prop.get("checkbox"), bool):
            raise AdapterRefusal(
                "notion",
                "The Notion row has no readable Locked checkbox, so PriceQuorum cannot tell whether it may be changed.",
                "Add a checkbox property named Locked to the pricing data source. " + _SCHEMA_REMEDY,
            )
        if current.locked:
            raise AdapterRefusal(
                "notion",
                f"The Notion row {current.label or external_id} is locked.",
                "Uncheck Locked on the Notion row, or ask its owner, then run the change again.",
            )
        price_prop = props.get("Price")
        if not isinstance(price_prop, dict) or "number" not in price_prop:
            raise AdapterRefusal(
                "notion",
                "The Notion row has no number property named Price.",
                "Make Price a number property. " + _SCHEMA_REMEDY,
            )
        currency_name = _select(props.get("Currency"))
        if currency_name is None:
            raise AdapterRefusal(
                "notion",
                "The Notion row has no Currency, so the price being replaced cannot be checked.",
                "Set Currency on the Notion row to the currency Stripe bills this plan in.",
            )
        if currency_name.lower() != amount.currency:
            raise AdapterRefusal(
                "notion",
                f"The Notion row is priced in {currency_name.lower()}, not {amount.currency}.",
                "Change the plan that is priced in this currency, or fix the Currency on the Notion row.",
            )
        call_site = "notion.page.update"
        body = self._request(
            call_site,
            "PATCH",
            f"/pages/{external_id}",
            {"properties": {"Price": {"number": major_json_number(amount.minor_units, amount.currency)}}},
        )
        _page_properties(body, call_site, external_id)
        self._faults.after(call_site)
        return WriteResult(external_object_id=external_id)

    def read_back(self, external_id: str) -> Readback:
        record, _ = self._fetch(external_id)
        return Readback(
            app="notion",
            value=record.price,
            raw_value=record.raw_value,
            read_at=datetime.now(UTC),
            source_id=external_id,
        )
