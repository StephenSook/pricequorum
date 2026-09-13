"""The drift monitor: detection in minor units, polling only while someone listens, the SSE stream with
CORS, and the operator heal run that writes derived surfaces only."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI
from sse_starlette.sse import AppStatus

from pricequorum.adapters_factory import AdapterSet
from pricequorum.api.app import create_app
from pricequorum.config import Settings
from pricequorum.monitor import DriftMonitor
from pricequorum.orchestrator import HEAL_APPROVER
from pricequorum.ports import Money
from tests.fakes import world
from tests.runlog import ledger_steps, payloads

OPERATOR = {"X-Operator-Token": "operator-test-token"}
ORIGIN = "https://pricequorum-web.vercel.app"


def page_of(surface: Any, plan: str) -> str:
    return next(record_id for record_id, row in surface.rows.items() if row["pq_plan_id"] == plan)


def test_a_check_reports_ok_then_each_drift_once_then_ok_again() -> None:
    stripe, notion, airtable = world()
    monitor = DriftMonitor(AdapterSet(stripe, notion, airtable, None))

    assert monitor.check() == []
    assert [e["type"] for e in monitor.events_after(0)] == ["monitor.ok"]

    notion.rows[page_of(notion, "pro")]["value"] = 21.0
    drifts = monitor.check()
    assert [(d.plan_key, d.app, d.expected, d.observed) for d in drifts] == [
        ("pro", "notion", Money(2000, "usd"), Money(2100, "usd"))
    ]
    seen = monitor.last_seq
    monitor.check()
    assert monitor.events_after(seen) == []
    assert [e["type"] for e in monitor.snapshot()] == ["drift.detected"]

    notion.rows[page_of(notion, "pro")]["value"] = 20.0
    monitor.check()
    assert [e["type"] for e in monitor.events_after(seen)] == ["monitor.ok"]
    assert [e["type"] for e in monitor.snapshot()] == ["monitor.ok"]


def test_a_plan_claimed_by_two_stripe_products_is_not_compared() -> None:
    stripe, notion, airtable = world()
    stripe.add_plan("pro", "Pro copy", Money(999, "usd"))
    monitor = DriftMonitor(AdapterSet(stripe, notion, airtable, None))
    assert monitor.check() == []


def test_unconfigured_apps_are_reported_not_hidden() -> None:
    monitor = DriftMonitor(AdapterSet())
    assert monitor.check() == []
    error = monitor.events_after(0)[0]
    assert error["type"] == "monitor.error" and error["payload"]["remedy"]


def test_the_monitor_reads_the_apps_only_while_someone_listens() -> None:
    stripe, notion, airtable = world()
    monitor = DriftMonitor(AdapterSet(stripe, notion, airtable, None), interval_seconds=0.02)
    stop = threading.Event()
    thread = threading.Thread(target=monitor.run, args=(stop,), daemon=True)
    thread.start()
    try:
        time.sleep(0.2)
        assert monitor.checks == 0
        monitor.add_listener()
        deadline = time.monotonic() + 5
        while monitor.checks < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert monitor.checks >= 3
        monitor.remove_listener()
        time.sleep(0.1)
        settled = monitor.checks
        time.sleep(0.3)
        assert monitor.checks <= settled + 1
    finally:
        stop.set()
        monitor.trigger()
        thread.join(5)


@contextmanager
def served(app: FastAPI) -> Iterator[str]:
    """Runs the app under a real uvicorn server, because an endless event stream needs a real connection."""
    AppStatus.should_exit_event = None
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=2))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(20)
        sock.close()
        AppStatus.should_exit = False


def test_the_stream_shows_drift_and_the_operator_heal_repairs_it(settings: Settings) -> None:
    stripe, notion, airtable = world()
    notion.rows[page_of(notion, "pro")]["value"] = 21.0
    app = create_app(settings, AdapterSet(stripe, notion, airtable, None))
    with served(app) as base, httpx.Client(base_url=base, timeout=15) as http:
        with http.stream("GET", "/api/monitor/events", headers={"Origin": ORIGIN}) as response:
            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == ORIGIN
            envelope: dict[str, Any] = {}
            for line in response.iter_lines():
                if line.startswith("data:"):
                    envelope = json.loads(line[5:])
                    if envelope["type"] == "drift.detected":
                        break
        assert envelope["type"] == "drift.detected" and isinstance(envelope["seq"], int)
        drift = envelope["payload"]
        assert drift == {
            "plan_key": "pro",
            "app": "notion",
            "expected": {"minor_units": 2000, "currency": "usd"},
            "observed": {"minor_units": 2100, "currency": "usd"},
            "raw_value": "21.0",
            "detected_at": drift["detected_at"],
        }

        assert http.post("/api/monitor/heal", json={"plan_key": "pro"}).status_code == 403
        started = http.post("/api/monitor/heal", json={"plan_key": "pro"}, headers=OPERATOR)
        assert started.status_code == 202
        run_id = started.json()["run_id"]

        monitor = app.state.monitor
        deadline = time.monotonic() + 20
        healed: list[dict[str, Any]] = []
        while not healed and time.monotonic() < deadline:
            healed = [e["payload"] for e in monitor.events_after(0) if e["type"] == "drift.healed"]
            time.sleep(0.05)
        assert healed == [{"plan_key": "pro", "app": "notion", "run_id": run_id}]

        summary = http.get(f"/api/runs/{run_id}").json()
        assert summary["outcome"] == "SUCCESS"
        assert (summary["approval"]["mode"], summary["approval"]["approver_display"]) == ("operator", HEAL_APPROVER)
        assert ledger_steps(run_id) == [("notion", "update_price")]
        assert payloads(run_id, "policy.decided")[-1]["rule"] == "heal_derived"
        assert notion.value_for("pro") == 20.0 and stripe.creates == 0
