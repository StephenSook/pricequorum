"""The HTTP surface: health, runs, the event stream with replay and CORS, operator approval, the
ledger endpoints, evaluation results and proof."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from nacl.signing import VerifyKey
from sse_starlette.sse import AppStatus

from pricequorum.adapters_factory import AdapterSet
from pricequorum.api.app import create_app
from pricequorum.config import Settings
from tests.fakes import world

OPERATOR = {"X-Operator-Token": "operator-test-token"}
ORIGIN = "https://pricequorum-web.vercel.app"


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    AppStatus.should_exit_event = None  # sse-starlette keeps one event per loop; each TestClient has its own loop
    stripe, notion, airtable = world()
    app = create_app(settings, AdapterSet(stripe, notion, airtable, None))
    with TestClient(app) as test_client:
        yield test_client


def wait_for_outcome(client: TestClient, run_id: str, timeout: float = 15) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = client.get(f"/api/runs/{run_id}/events.json").json()
        if events and events[-1]["type"] == "run.outcome":
            return events
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish")


def wait_for_type(client: TestClient, run_id: str, type_name: str, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(e["type"] == type_name for e in client.get(f"/api/runs/{run_id}/events.json").json()):
            return
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} never emitted {type_name}")


def test_health_reports_each_part_honestly(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["db"] == "ok" and body["stripe_mode"] == "test"
    assert body["slack_socket"] == "down" and body["ok"] is False
    assert body["apps"] == {
        "stripe": "configured",
        "notion": "configured",
        "airtable": "configured",
        "approval": "not configured",
    }


def test_a_run_waits_for_the_operator_then_succeeds(client: TestClient) -> None:
    created = client.post("/api/runs", json={"request_text": "raise Pro to $25/month"})
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    assert created.json()["events_url"] == f"/api/runs/{run_id}/events"
    wait_for_type(client, run_id, "approval.requested")

    assert client.post(f"/api/runs/{run_id}/approval", json={"decision": "approve"}).status_code == 401
    approved = client.post(f"/api/runs/{run_id}/approval", json={"decision": "approve"}, headers=OPERATOR)
    assert approved.json() == {"decision": "APPROVED"}
    assert client.post(f"/api/runs/{run_id}/approval", json={"decision": "deny"}, headers=OPERATOR).status_code == 409

    events = wait_for_outcome(client, run_id)
    assert events[-1]["payload"]["outcome"] == "SUCCESS"
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))

    summary = client.get(f"/api/runs/{run_id}").json()
    assert summary["outcome"] == "SUCCESS" and summary["approval"]["mode"] == "operator"
    assert summary["resolution"]["stripe_price_id_new"] and summary["invariants_expected"]
    assert {r["app"] for r in summary["readback"]} == {"stripe", "notion", "airtable"}
    assert all(row["state"] == "completed" and row["entry_hash"] for row in summary["ledger"])


def test_eval_only_options_need_the_operator_token(client: TestClient) -> None:
    body = {"request_text": "raise Pro to $25/month", "approval_mode": "sandbox_auto"}
    refused = client.post("/api/runs", json=body)
    assert refused.status_code == 403 and refused.json()["remedy"]
    assert client.post("/api/runs", json={**body, "fault": "no_such_fault"}, headers=OPERATOR).status_code == 422
    accepted = client.post("/api/runs", json={**body, "fault": "timeout_after_commit"}, headers=OPERATOR)
    assert accepted.status_code == 202
    events = wait_for_outcome(client, accepted.json()["run_id"])
    assert events[-1]["payload"]["outcome"] in ("SUCCESS", "NEEDS_HUMAN")


def test_the_stream_replays_after_last_event_id_with_cors(client: TestClient) -> None:
    run_id = client.post("/api/runs", json={"request_text": "Sync Pro from Notion"}).json()["run_id"]
    total = len(wait_for_outcome(client, run_id))
    with client.stream(
        "GET", f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "1", "Origin": ORIGIN}
    ) as response:
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert response.headers["content-type"].startswith("text/event-stream")
        ids = [int(line.split(":", 1)[1]) for line in response.iter_lines() if line.startswith("id:")]
    assert ids == list(range(2, total + 1))


def test_unknown_runs_and_bad_requests_return_the_error_shape(client: TestClient) -> None:
    missing = client.get("/api/runs/00000000-0000-4000-8000-000000000000/events.json")
    assert missing.status_code == 404 and set(missing.json()) == {"error", "detail", "remedy"}
    invalid = client.post("/api/runs", json={"request_text": ""})
    assert invalid.status_code == 422 and invalid.json()["error"] == "validation_error"


def test_ledger_export_and_verify_agree_and_the_signature_checks(client: TestClient) -> None:
    run_id = client.post("/api/runs", json={"request_text": "Just edit the amount in place"}).json()["run_id"]
    wait_for_outcome(client, run_id)
    exported = client.get("/api/ledger/export").json()
    assert exported["rows"] and exported["genesis"] == "00" * 32
    VerifyKey(bytes.fromhex(exported["public_key"])).verify(
        bytes.fromhex(exported["head"]), bytes.fromhex(exported["signature"])
    )
    verified = client.post("/api/ledger/verify").json()
    assert verified["ok"] is True and verified["head"] == exported["head"]
    assert client.get("/api/public-key").json() == {"public_key": exported["public_key"], "algorithm": "ed25519"}


def test_proof_is_zero_until_an_eval_run_is_recorded(client: TestClient) -> None:
    empty = client.get("/api/proof").json()
    assert empty["scenarios"] == {"passed": 0, "total": 0, "wilson_95": None, "runs_per_scenario": None}
    assert empty["named_failures"] == [] and empty["last_eval_run_at"] is None

    run = {
        "commit_sha": "abc1234",
        "results": [
            {
                "scenario_id": "happy_path",
                "description": "Set Pro to 25",
                "expected_outcome": "SUCCESS",
                "observed_outcome": "SUCCESS",
                "passed": True,
            },
            {
                "scenario_id": "locked_record",
                "expected_outcome": "REFUSED",
                "observed_outcome": "REFUSED",
                "passed": True,
                "forbidden_refused": 1,
                "forbidden_attempted": 1,
            },
            {
                "scenario_id": "stale_read",
                "expected_outcome": "PARTIAL",
                "observed_outcome": "SUCCESS",
                "passed": False,
                "detail": "cache served first",
            },
        ],
    }
    assert client.post("/api/evals/results", json=run).status_code == 403
    recorded = client.post("/api/evals/results", json=run, headers=OPERATOR)
    assert recorded.status_code == 201 and recorded.json()["results"] == 3

    proof = client.get("/api/proof").json()
    assert (proof["scenarios"]["passed"], proof["scenarios"]["total"]) == (2, 3)
    assert proof["forbidden_actions_refused"] == {"refused": 1, "attempted": 1}
    assert proof["named_failures"] == [{"scenario_id": "stale_read", "explanation": "cache served first"}]
    latest = client.get("/api/evals/latest").json()
    assert [r["scenario_id"] for r in latest["results"]] == ["happy_path", "locked_record", "stale_read"]
    assert latest["commit_sha"] == "abc1234"
