"""Airtable, the derived SKU catalogue. Follows Stripe, never the other way.

Writes are upserts merged on pq_plan_id with JSON numbers. After a 429 the adapter waits the
30 seconds Airtable asks for. The Locked checkbox is read before every write.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from pricequorum.adapters._http import Sleep, airtable_penalty, request_json
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

AIRTABLE_API = "https://api.airtable.com/v0"
_INTERVALS: tuple[Interval, ...] = ("month", "year")


def _remedy(status: int, body: dict[str, Any]) -> str:
    error = body.get("error")
    kind = error.get("type") if isinstance(error, dict) else error
    if status in (401, 403) or kind in ("AUTHENTICATION_REQUIRED", "INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND"):
        return "Check AIRTABLE_PAT has data.records:read and data.records:write for this base."
    if status == 404 or kind in ("NOT_FOUND", "TABLE_NOT_FOUND", "MODEL_ID_NOT_FOUND"):
        return "Check AIRTABLE_BASE_ID and AIRTABLE_TABLE, and that the record still exists."
    if kind == "INVALID_VALUE_FOR_COLUMN" or status == 422:
        return "Check the table has pq_plan_id (text), Name, Price (number), Currency, Interval and Locked (checkbox)."
    return "Check the Airtable base configuration and try again."


class AirtableAdapter:
    app: AppName = "airtable"

    def __init__(
        self,
        pat: str,
        base_id: str,
        table: str,
        faults: FaultInjector,
        client: httpx.Client | None = None,
        sleep: Sleep = time.sleep,
        jitter: Callable[[], float] | None = None,
        max_retries: int = 2,
    ) -> None:
        self._base_path = f"/{base_id}/{quote(table, safe='')}"
        self._faults = faults
        self._client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
        self._sleep = sleep
        self._max_retries = max_retries
        self._retry_delay = (
            (lambda attempt, response: airtable_penalty(attempt, response, jitter)) if jitter else airtable_penalty
        )
        self._headers = {"Authorization": f"Bearer {pat}", "Content-Type": "application/json"}

    def _request(
        self,
        call_site: str,
        method: str,
        path: str = "",
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return request_json(
            self._client,
            app="airtable",
            call_site=call_site,
            method=method,
            url=f"{AIRTABLE_API}{self._base_path}{path}",
            headers=self._headers,
            json=json,
            params=params,
            sleep=self._sleep,
            max_retries=self._max_retries,
            retry_delay=self._retry_delay,
            remedy_for=_remedy,
        )

    @staticmethod
    def _parse(record: dict[str, Any]) -> PlanRecord:
        fields = record.get("fields") or {}
        currency_value = fields.get("Currency")
        currency = currency_value.lower() if isinstance(currency_value, str) and currency_value else None
        number = fields.get("Price")
        price: Money | None = None
        if currency is not None:
            minor = major_to_minor(number, currency)
            if minor is not None:
                try:
                    price = Money(minor, currency)
                except ValueError:
                    price = None
        interval = fields.get("Interval")
        pq_plan_id = fields.get("pq_plan_id")
        return PlanRecord(
            app="airtable",
            external_id=str(record.get("id")),
            pq_plan_id=str(pq_plan_id) if pq_plan_id else None,
            label=str(fields.get("Name") or ""),
            price=price,
            raw_value=None if number is None else str(number),
            interval=interval if interval in _INTERVALS else None,
            locked=bool(fields.get("Locked", False)),
        )

    def list_plans(self) -> list[PlanRecord]:
        plans: list[PlanRecord] = []
        offset: str | None = None
        while True:
            params: dict[str, Any] = {"pageSize": 100}
            if offset:
                params["offset"] = offset
            page = self._request("airtable.list", "GET", params=params)
            plans.extend(self._parse(record) for record in page.get("records") or [])
            offset = page.get("offset")
            if not offset:
                return plans

    def _record(self, record_id: str) -> PlanRecord:
        return self._parse(self._request("airtable.record.retrieve", "GET", f"/{record_id}"))

    def write_price(self, external_id: str, amount: Money, idempotency_key: str) -> WriteResult:
        # An upsert that sets an absolute value, merged on pq_plan_id, is idempotent by construction.
        current = self._record(external_id)
        if current.locked:
            raise AdapterRefusal(
                "airtable",
                f"The Airtable record {current.label or external_id} is locked.",
                "Uncheck Locked on the Airtable record, or ask its owner, then run the change again.",
            )
        if not current.pq_plan_id:
            raise AdapterRefusal(
                "airtable",
                "The Airtable record has no pq_plan_id, so it cannot be matched safely.",
                "Add a pq_plan_id to the Airtable record that matches the Stripe product and the Notion row.",
            )
        if current.price is not None and current.price.currency != amount.currency:
            raise AdapterRefusal(
                "airtable",
                f"The Airtable record is priced in {current.price.currency}, not {amount.currency}.",
                "Change the plan that is priced in this currency, or fix the Currency on the Airtable record.",
            )
        body = {
            "performUpsert": {"fieldsToMergeOn": ["pq_plan_id"]},
            "records": [
                {
                    "fields": {
                        "pq_plan_id": current.pq_plan_id,
                        "Price": major_json_number(amount.minor_units, amount.currency),
                    }
                }
            ],
        }
        result = self._request("airtable.upsert", "PATCH", json=body)
        self._faults.after("airtable.upsert")
        if result.get("createdRecords"):
            raise AdapterRefusal(
                "airtable",
                "The upsert created a new Airtable record instead of updating the existing one.",
                "Make pq_plan_id unique in the Airtable table, then delete the duplicate record.",
            )
        updated = result.get("updatedRecords") or [record.get("id") for record in result.get("records") or []]
        return WriteResult(external_object_id=str(updated[0]) if updated else external_id)

    def read_back(self, external_id: str) -> Readback:
        record = self._record(external_id)
        return Readback(
            app="airtable",
            value=record.price,
            raw_value=record.raw_value,
            read_at=datetime.now(UTC),
            source_id=external_id,
        )
