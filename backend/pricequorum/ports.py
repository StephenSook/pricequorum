"""The adapter seam of the PriceQuorum backend.

The run orchestrator talks to Stripe, Notion, Airtable and Slack only through these
protocols, so the core and the adapters can be built and tested separately.

Rules every adapter follows:
- Money crosses this seam as integer minor units with a lowercase ISO 4217 code. Never a float.
- A transport failure raises AdapterFault. The write may or may not have landed, so the caller
  must read the app back before deciding whether to retry (with the same idempotency key).
- A business refusal (locked record, missing field, live Stripe key) raises AdapterRefusal with
  a remedy. It is never retried.
- Nothing is invented: a value the app did not return is None.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

AppName = Literal["stripe", "notion", "airtable", "slack"]
FaultKind = Literal["timeout", "rate_limit", "conflict_409", "server_5xx"]
Interval = Literal["month", "year"]
DecisionWord = Literal["approve", "deny"]

_CURRENCY = re.compile(r"^[a-z]{3}$")


@dataclass(frozen=True)
class Money:
    minor_units: int
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.minor_units, bool) or not isinstance(self.minor_units, int):
            raise TypeError("minor_units must be an int")
        if not _CURRENCY.fullmatch(self.currency):
            raise ValueError("currency must be a lowercase ISO 4217 code")

    def to_json(self) -> dict[str, object]:
        return {"minor_units": self.minor_units, "currency": self.currency}


@dataclass(frozen=True)
class PlanRecord:
    """One plan exactly as one app stores it."""

    app: AppName
    external_id: str  # Stripe product id, Notion page id, or Airtable record id
    pq_plan_id: str | None  # the shared key, when the record carries one
    label: str  # human name, used only by the fuzzy resolver
    price: Money | None  # current price, None when unreadable
    raw_value: str | None  # what the app literally stores, for display
    interval: Interval | None
    locked: bool  # Notion and Airtable "Locked" checkbox; always False for Stripe
    price_id: str | None = None  # Stripe only: the product's current default price id


@dataclass(frozen=True)
class Readback:
    """A fresh read of one app, made after the writes."""

    app: AppName
    value: Money | None
    raw_value: str | None
    read_at: datetime  # timezone-aware UTC
    source_id: str  # the external id that was read


@dataclass(frozen=True)
class WriteResult:
    external_object_id: str
    replayed: bool = False  # True when the app says this idempotency key was already used


class AdapterFault(Exception):
    """A transport failure after the request may have reached the app."""

    def __init__(self, kind: FaultKind, call_site: str, injected: bool, detail: str = "") -> None:
        super().__init__(f"{call_site}: {kind}{' (injected)' if injected else ''} {detail}".strip())
        self.kind: FaultKind = kind
        self.call_site = call_site
        self.injected = injected


class AdapterRefusal(Exception):
    """The app refused on business grounds. Carries the remedy shown to the person."""

    def __init__(self, app: AppName, reason: str, remedy: str) -> None:
        super().__init__(reason)
        self.app: AppName = app
        self.reason = reason
        self.remedy = remedy


class FaultInjector(Protocol):
    """Raises an injected AdapterFault right AFTER a real request was sent, when armed for that call site."""

    def after(self, call_site: str) -> None: ...


class StripePort(Protocol):
    def list_plans(self) -> list[PlanRecord]: ...

    def create_price(
        self, product_id: str, amount: Money, interval: Interval, lookup_key: str, idempotency_key: str
    ) -> WriteResult: ...

    def set_default_price(self, product_id: str, price_id: str, idempotency_key: str) -> WriteResult: ...

    def archive_price(self, price_id: str, idempotency_key: str) -> WriteResult: ...

    def find_active_price(self, product_id: str, amount: Money, interval: Interval) -> str | None:
        """Read-back used for recovery: the id of an active price with this amount, if one landed."""
        ...

    def find_created_price(
        self, product_id: str, amount: Money, interval: Interval, lookup_key: str, idempotency_key: str
    ) -> str | None:
        """Read-back used to recover a create: the price this idempotency key created, if it landed. A price
        with the same amount that anything else created is never returned."""
        ...

    def price_is_archived(self, price_id: str) -> bool:
        """Read-back used to recover an archive: whether this exact price is inactive."""
        ...

    def read_back(self, product_id: str) -> Readback: ...


class DerivedPort(Protocol):
    """Notion and Airtable: derived surfaces that follow Stripe."""

    app: AppName

    def list_plans(self) -> list[PlanRecord]: ...

    def write_price(self, external_id: str, amount: Money, idempotency_key: str) -> WriteResult: ...

    def read_back(self, external_id: str) -> Readback: ...


@dataclass(frozen=True)
class ApprovalRequest:
    run_id: str
    summary: str
    args_hash: str
    expires_at: datetime


@dataclass(frozen=True)
class ApprovalPosted:
    channel: str
    ts: str


class DecisionHandler(Protocol):
    def __call__(self, run_id: str, decision: DecisionWord, approver_display: str, args_hash: str) -> str:
        """Applies a decision with a single-winner transition. Returns APPROVED, DENIED, EXPIRED or ALREADY_DECIDED."""
        ...


class ApprovalPort(Protocol):
    def start(self, on_decision: DecisionHandler) -> None:
        """Connects (Slack Socket Mode) and routes button presses to on_decision."""
        ...

    def connected(self) -> bool: ...

    def post_request(self, request: ApprovalRequest) -> ApprovalPosted: ...

    def post_outcome(self, posted: ApprovalPosted, decision: str, approver_display: str | None) -> None:
        """Replaces the buttons with the final decision so the Slack message cannot be pressed twice."""
        ...
