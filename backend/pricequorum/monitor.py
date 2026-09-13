"""The drift monitor: does Notion or Airtable show a price different from Stripe, in integer minor units?

Built for one free web instance. It runs on a daemon thread in the API process and reads the three apps only
while someone listens on GET /api/monitor/events (every PQ_MONITOR_INTERVAL_SECONDS, default 60) or when the
judge sandbox asks for a check. It never writes. POST /api/monitor/heal starts a heal run that does, through
the ledger, and drift.healed is published only after that run verifies SUCCESS on fresh reads.

Events are kept in memory (the last 200). They describe the current state of the apps, not history, so a
restart loses nothing a new check cannot rebuild.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pricequorum.adapters_factory import AdapterSet
from pricequorum.events import now_iso
from pricequorum.ports import AdapterFault, AdapterRefusal, Money, PlanRecord
from pricequorum.resolver import key_of

if TYPE_CHECKING:
    from pricequorum.orchestrator import Orchestrator

log = logging.getLogger("pricequorum.monitor")

EVENT_TYPES = ("monitor.ok", "monitor.error", "drift.detected", "drift.healed")


@dataclass(frozen=True)
class Drift:
    plan_key: str
    app: str
    expected: Money
    observed: Money | None
    raw_value: str | None

    def payload(self, detected_at: str) -> dict[str, Any]:
        return {
            "plan_key": self.plan_key,
            "app": self.app,
            "expected": self.expected.to_json(),
            "observed": self.observed.to_json() if self.observed else None,
            "raw_value": self.raw_value,
            "detected_at": detected_at,
        }


def find_drift(
    stripe_plans: list[PlanRecord],
    notion_plans: list[PlanRecord],
    airtable_plans: list[PlanRecord],
    plan_keys: set[str] | None = None,
) -> list[Drift]:
    """Every Notion or Airtable record whose price differs from the Stripe price of the plan with the same
    pq_plan_id. A plan claimed by two Stripe products has no single expected price and is not compared."""
    wanted = {key_of(key) for key in plan_keys} if plan_keys is not None else None
    owners: dict[str, list[PlanRecord]] = defaultdict(list)
    for plan in stripe_plans:
        if plan.pq_plan_id and plan.price is not None:
            owners[key_of(plan.pq_plan_id)].append(plan)
    drifts: list[Drift] = []
    for key, sources in owners.items():
        if len(sources) != 1 or (wanted is not None and key not in wanted):
            continue
        source = sources[0]
        assert source.price is not None and source.pq_plan_id is not None
        for app, records in (("notion", notion_plans), ("airtable", airtable_plans)):
            for record in records:
                if record.pq_plan_id and key_of(record.pq_plan_id) == key and record.price != source.price:
                    drifts.append(Drift(source.pq_plan_id, app, source.price, record.price, record.raw_value))
    return drifts


class DriftMonitor:
    def __init__(self, adapters: AdapterSet, interval_seconds: float = 60.0, buffer_size: int = 200) -> None:
        self.adapters = adapters
        self.interval_seconds = interval_seconds
        self.checks = 0
        self._events: deque[dict[str, Any]] = deque(maxlen=buffer_size)
        self._seq = 0
        self._lock = threading.RLock()
        self._check_lock = threading.Lock()
        self._listeners = 0
        self._wake = threading.Event()
        self._known: dict[tuple[str, str], dict[str, Any]] = {}
        self._last_ok: dict[str, Any] | None = None

    # Events ------------------------------------------------------------------------

    def publish(self, type_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if type_name not in EVENT_TYPES:
            raise ValueError(f"unknown monitor event {type_name}")
        with self._lock:
            self._seq += 1
            envelope = {"seq": self._seq, "type": type_name, "at": now_iso(), "payload": payload}
            self._events.append(envelope)
            return envelope

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def events_after(self, seq: int) -> list[dict[str, Any]]:
        with self._lock:
            return [envelope for envelope in self._events if envelope["seq"] > seq]

    def snapshot(self) -> list[dict[str, Any]]:
        """The events that describe the current state: open drifts, or the last clean check."""
        with self._lock:
            if self._known:
                return sorted(self._known.values(), key=lambda envelope: envelope["seq"])
            return [self._last_ok] if self._last_ok is not None else []

    # Listeners and the polling loop ------------------------------------------------

    @property
    def listeners(self) -> int:
        with self._lock:
            return self._listeners

    def add_listener(self) -> None:
        with self._lock:
            self._listeners += 1
        self._wake.set()

    def remove_listener(self) -> None:
        with self._lock:
            self._listeners = max(0, self._listeners - 1)

    def trigger(self) -> None:
        self._wake.set()

    def run(self, stop: threading.Event) -> None:
        """Checks when woken, and every interval while at least one listener is connected."""
        while True:
            woken = self._wake.wait(self.interval_seconds)
            self._wake.clear()
            if stop.is_set():
                return
            if woken or self.listeners > 0:
                try:
                    self.check()
                except Exception:  # noqa: BLE001 - the monitor thread must keep running
                    log.exception("drift check failed")

    # Checks ------------------------------------------------------------------------

    def check(self, plan_keys: set[str] | None = None) -> list[Drift]:
        with self._check_lock:
            self.checks += 1
            checked_at = now_iso()
            stripe, notion, airtable = self.adapters.stripe, self.adapters.notion, self.adapters.airtable
            if stripe is None or notion is None or airtable is None:
                names = ", ".join(name.capitalize() for name in self.adapters.missing_apps())
                self.publish(
                    "monitor.error",
                    {
                        "checked_at": checked_at,
                        "detail": f"{names} not configured, so drift cannot be checked.",
                        "remedy": f"Set the credentials for {names} on the backend and restart it.",
                    },
                )
                return []
            try:
                plans = (stripe.list_plans(), notion.list_plans(), airtable.list_plans())
            except AdapterRefusal as refusal:
                self.publish(
                    "monitor.error", {"checked_at": checked_at, "detail": refusal.reason, "remedy": refusal.remedy}
                )
                return []
            except AdapterFault as fault:
                self.publish(
                    "monitor.error",
                    {
                        "checked_at": checked_at,
                        "detail": str(fault),
                        "remedy": "The monitor reads the apps again on its next check.",
                    },
                )
                return []
            drifts = find_drift(*plans, plan_keys=plan_keys)
            wanted = {key_of(key) for key in plan_keys} if plan_keys is not None else None
            with self._lock:
                current = {(drift.plan_key, drift.app) for drift in drifts}
                for drift in drifts:
                    payload = drift.payload(checked_at)
                    known = self._known.get((drift.plan_key, drift.app))
                    if (
                        known is not None
                        and known["payload"]["expected"] == payload["expected"]
                        and known["payload"]["observed"] == payload["observed"]
                    ):
                        continue
                    self._known[(drift.plan_key, drift.app)] = self.publish("drift.detected", payload)
                gone = [
                    key for key in self._known if key not in current and (wanted is None or key_of(key[0]) in wanted)
                ]
                for key in gone:
                    del self._known[key]
                if not self._known:
                    self._last_ok = self.publish("monitor.ok", {"checked_at": checked_at})
            return drifts

    def mark_healed(self, plan_key: str, apps: list[str], run_id: str) -> None:
        with self._lock:
            for app in apps:
                self.publish("drift.healed", {"plan_key": plan_key, "app": app, "run_id": run_id})
                for key in [k for k in self._known if key_of(k[0]) == key_of(plan_key) and k[1] == app]:
                    del self._known[key]


def heal_and_report(orchestrator: Orchestrator, monitor: DriftMonitor, run_id: str, plan_key: str) -> list[str]:
    """Runs the heal, publishes drift.healed for each app it repaired, then confirms with a fresh check."""
    healed = orchestrator.execute_heal(run_id, plan_key)
    if healed:
        monitor.mark_healed(plan_key, healed, run_id)
    monitor.check({plan_key})
    return healed
