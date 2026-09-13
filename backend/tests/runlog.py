"""Reads what a run recorded, for assertions."""

from __future__ import annotations

from typing import Any

from pricequorum import db
from pricequorum.events import list_events


def types(run_id: str) -> list[str]:
    return [event["type"] for event in list_events(run_id)]


def payloads(run_id: str, type_name: str) -> list[dict[str, Any]]:
    return [event["payload"] for event in list_events(run_id) if event["type"] == type_name]


def outcome(run_id: str) -> dict[str, Any]:
    finals = payloads(run_id, "run.outcome")
    assert finals, f"run {run_id} has no run.outcome"
    return finals[-1]


def ledger_steps(run_id: str) -> list[tuple[str, str]]:
    with db.connect() as conn:
        rows = conn.execute("select app, action from action_ledger where run_id = %s order by id", (run_id,)).fetchall()
    return [(row["app"], row["action"]) for row in rows]
