"""Airtable, the derived SKU catalogue. Follows Stripe, never the other way.

A price write updates the one known record through the single-record endpoint with typecast off.
That call cannot create a record, so if the record was deleted after it was read, the write fails
instead of silently adding a duplicate. After a 429 the adapter waits the 30 seconds Airtable
asks for. The Locked checkbox, the pq_plan_id and the Currency are checked before every write.
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

AIRTABLE_API = "https://api.airtable.com/v0"
_INTERVALS: tuple[Interval, ...] = ("month", "year")
# The call site name predates the switch from upsert to single-record update. It is kept because
# fault plans and run events already refer to it.
WRITE_CALL_SITE = "airtable.upsert"


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


def _record_fields(body: dict[str, Any], call_site: str, expected_id: str | None) -> dict[str, Any]:
    """Checks the body is a record (and the requested one). A malformed success body is a fault."""
    fields = body.get("fields")
    record_id = body.get("id")
    if not isinstance(record_id, str) or not isinstance(fields, dict):
        raise AdapterFault("server_5xx", call_site, False, "Airtable answered without a readable record")
    if expected_id is not None and record_id != expected_id:
        raise AdapterFault("server_5xx", call_site, False, "Airtable answered with a different record than requested")
    return fields


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
    def _parse(record_id: str, fields: dict[str, Any]) -> PlanRecord:
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
            external_id=record_id,
            pq_plan_id=str(pq_plan_id) if pq_plan_id else None,
            label=str(fields.get("Name") or ""),
            price=price,
            raw_value=None if number is None else str(number),
            interval=interval if interval in _INTERVALS else None,
            locked=fields.get("Locked") is True,
        )

    def list_plans(self) -> list[PlanRecord]:
        plans: list[PlanRecord] = []
        offset: str | None = None
        call_site = "airtable.list"
        while True:
            params: dict[str, Any] = {"pageSize": 100}
            if offset:
                params["offset"] = offset
            page = self._request(call_site, "GET", params=params)
            records = page.get("records")
            if not isinstance(records, list):
                raise AdapterFault("server_5xx", call_site, False, "Airtable answered a list without a records array")
            for record in records:
                if not isinstance(record, dict):
                    raise AdapterFault("server_5xx", call_site, False, "Airtable listed a record that is not an object")
                plans.append(self._parse(str(record.get("id")), _record_fields(record, call_site, None)))
            offset = page.get("offset")
            if not offset:
                return plans

    def _fetch(self, record_id: str) -> tuple[PlanRecord, dict[str, Any]]:
        call_site = "airtable.record.retrieve"
        fields = _record_fields(self._request(call_site, "GET", f"/{record_id}"), call_site, record_id)
        return self._parse(record_id, fields), fields

    def write_price(self, external_id: str, amount: Money, idempotency_key: str) -> WriteResult:
        # Setting an absolute value on one known record id is idempotent and can never create a record.
        current, fields = self._fetch(external_id)
        locked = fields.get("Locked", False)  # Airtable omits an unchecked checkbox
        if not isinstance(locked, bool):
            raise AdapterRefusal(
                "airtable",
                "The Airtable record's Locked field is not a checkbox, so PriceQuorum cannot tell whether it may change.",
                "Make Locked a checkbox field in the Airtable table.",
            )
        if locked:
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
        currency_value = fields.get("Currency")
        if not isinstance(currency_value, str) or not currency_value.strip():
            raise AdapterRefusal(
                "airtable",
                "The Airtable record has no Currency, so the price being replaced cannot be checked.",
                "Set Currency on the Airtable record to the currency Stripe bills this plan in.",
            )
        if currency_value.strip().lower() != amount.currency:
            raise AdapterRefusal(
                "airtable",
                f"The Airtable record is priced in {currency_value.strip().lower()}, not {amount.currency}.",
                "Change the plan that is priced in this currency, or fix the Currency on the Airtable record.",
            )
        body = {"fields": {"Price": major_json_number(amount.minor_units, amount.currency)}, "typecast": False}
        result = self._request(WRITE_CALL_SITE, "PATCH", f"/{external_id}", json=body)
        _record_fields(result, WRITE_CALL_SITE, external_id)
        self._faults.after(WRITE_CALL_SITE)
        return WriteResult(external_object_id=external_id)

    def read_back(self, external_id: str) -> Readback:
        record, _ = self._fetch(external_id)
        return Readback(
            app="airtable",
            value=record.price,
            raw_value=record.raw_value,
            read_at=datetime.now(UTC),
            source_id=external_id,
        )
