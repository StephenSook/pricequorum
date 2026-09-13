"""Notion, the derived public pricing page. Follows Stripe, never the other way.

Uses API version 2025-09-03, where a database's rows live in a data source. Rows are located by
their stored page id, never by title. The Locked checkbox is read before every write.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx

from pricequorum.adapters._http import Sleep, request_json, retry_after_or_backoff
from pricequorum.adapters._money import major_json_number, major_to_minor
from pricequorum.ports import (
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


def _remedy(status: int, body: dict[str, Any]) -> str:
    code = body.get("code")
    if code == "object_not_found" or status == 404:
        return "Share the pricing database with the PriceQuorum integration in Notion (the page menu, Connections)."
    if code in ("unauthorized", "restricted_resource") or status in (401, 403):
        return "Check NOTION_TOKEN and that the integration has read, update and insert content capabilities."
    if code == "validation_error":
        return "Check the data source has the properties Name, pq_plan_id, Price, Currency, Interval and Locked."
    return "Check the Notion data source configuration and try again."


def _text(prop: dict[str, Any] | None) -> str | None:
    if not prop:
        return None
    items = prop.get("title") or prop.get("rich_text") or []
    value = "".join(str(item.get("plain_text", "")) for item in items)
    return value or None


def _select(prop: dict[str, Any] | None) -> str | None:
    option = (prop or {}).get("select")
    return str(option["name"]) if isinstance(option, dict) and option.get("name") else None


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
    def _parse(page: dict[str, Any]) -> PlanRecord:
        props = page.get("properties") or {}
        currency_name = _select(props.get("Currency"))
        currency = currency_name.lower() if currency_name else None
        number = (props.get("Price") or {}).get("number")
        price: Money | None = None
        if currency is not None:
            minor = major_to_minor(number, currency)
            if minor is not None:
                try:
                    price = Money(minor, currency)
                except ValueError:
                    price = None
        interval = _select(props.get("Interval"))
        return PlanRecord(
            app="notion",
            external_id=str(page.get("id")),
            pq_plan_id=_text(props.get("pq_plan_id")),
            label=_text(props.get("Name")) or "",
            price=price,
            raw_value=None if number is None else str(number),
            interval=interval if interval in _INTERVALS else None,  # type: ignore[arg-type]
            locked=bool((props.get("Locked") or {}).get("checkbox", False)),
        )

    def list_plans(self) -> list[PlanRecord]:
        plans: list[PlanRecord] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            page = self._request(
                "notion.data_source.query", "POST", f"/data_sources/{self._data_source_id}/query", body
            )
            plans.extend(self._parse(item) for item in page.get("results") or [] if item.get("object") == "page")
            if not page.get("has_more") or not page.get("next_cursor"):
                return plans
            cursor = str(page["next_cursor"])

    def _record(self, page_id: str) -> PlanRecord:
        return self._parse(self._request("notion.page.retrieve", "GET", f"/pages/{page_id}"))

    def write_price(self, external_id: str, amount: Money, idempotency_key: str) -> WriteResult:
        # Notion has no idempotency keys; setting an absolute value is naturally idempotent.
        current = self._record(external_id)
        if current.locked:
            raise AdapterRefusal(
                "notion",
                f"The Notion row {current.label or external_id} is locked.",
                "Uncheck Locked on the Notion row, or ask its owner, then run the change again.",
            )
        if current.price is not None and current.price.currency != amount.currency:
            raise AdapterRefusal(
                "notion",
                f"The Notion row is priced in {current.price.currency}, not {amount.currency}.",
                "Change the plan that is priced in this currency, or fix the Currency on the Notion row.",
            )
        self._request(
            "notion.page.update",
            "PATCH",
            f"/pages/{external_id}",
            {"properties": {"Price": {"number": major_json_number(amount.minor_units, amount.currency)}}},
        )
        self._faults.after("notion.page.update")
        return WriteResult(external_object_id=external_id)

    def read_back(self, external_id: str) -> Readback:
        record = self._record(external_id)
        return Readback(
            app="notion",
            value=record.price,
            raw_value=record.raw_value,
            read_at=datetime.now(UTC),
            source_id=external_id,
        )
