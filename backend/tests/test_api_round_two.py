"""HTTP surfaces added for the evaluation suite and the judge: the mounted MCP server, the resolver match
endpoint, detection and concurrent eval rows, and the sandbox endpoints."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sse_starlette.sse import AppStatus

from pricequorum.adapters_factory import AdapterSet
from pricequorum.api.app import create_app
from pricequorum.config import Settings
from pricequorum.ports import Money
from tests.fakes import FakeStripe, sandbox_world, world

OPERATOR = {"X-Operator-Token": "operator-test-token"}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def wait_for_outcome(client: TestClient, run_id: str, timeout: float = 20) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = client.get(f"/api/runs/{run_id}/events.json").json()
        if events and events[-1]["type"] == "run.outcome":
            return events
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    AppStatus.should_exit_event = None
    stripe, notion, airtable = world()
    with TestClient(create_app(settings, AdapterSet(stripe, notion, airtable, None))) as test_client:
        yield test_client


@pytest.fixture
def sandbox_client(settings: Settings) -> Iterator[tuple[TestClient, FakeStripe]]:
    AppStatus.should_exit_event = None
    stripe, notion, airtable = sandbox_world()
    app = create_app(
        settings.model_copy(update={"pq_sandbox_cooldown_seconds": 30}), AdapterSet(stripe, notion, airtable, None)
    )
    with TestClient(app) as test_client:
        yield test_client, stripe


def test_the_mcp_server_is_mounted_and_lists_its_four_tools(client: TestClient) -> None:
    response = client.post(
        "/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, headers=MCP_HEADERS
    )
    assert response.status_code == 200, response.text
    names = sorted(tool["name"] for tool in response.json()["result"]["tools"])
    assert names == ["get_proof", "get_run", "run_price_change", "verify_chain"]


@pytest.mark.parametrize(
    ("left", "right", "match", "decision"),
    [
        (("Pro", "usd", "month"), ("pro", "usd", "month"), True, "fuzzy"),
        (("Pro", "usd", "month"), ("The Pro Plan", "usd", "month"), True, "fuzzy"),
        (("Pro", "usd", "month"), ("Pro", "eur", "month"), False, "different_currency"),
        (("Pro", "usd", "month"), ("Pro", "usd", "yearly"), False, "different_interval"),
        (("Pro", "usd", "month"), ("Pro Plus", "usd", "month"), False, "human"),
    ],
)
def test_resolver_match_applies_the_resolver_rules_to_one_pair(
    client: TestClient, left: tuple[str, str, str], right: tuple[str, str, str], match: bool, decision: str
) -> None:
    body = {
        "left": dict(zip(("label", "currency", "interval"), left, strict=True)),
        "right": dict(zip(("label", "currency", "interval"), right, strict=True)),
    }
    result = client.post("/api/resolver/match", json=body).json()
    assert (result["match"], result["decision"], result["threshold"]) == (match, decision, 90)
    assert isinstance(result["score"], int) and (result["score"] >= 90) == match


def test_resolver_match_validates_its_input(client: TestClient) -> None:
    bad = {"left": {"label": "Pro", "currency": "dollars"}, "right": {"label": "Pro", "currency": "usd"}}
    assert client.post("/api/resolver/match", json=bad).status_code == 422


def test_detection_rows_and_concurrent_outcomes_are_recorded_and_counted(client: TestClient) -> None:
    run = {
        "commit_sha": "def5678",
        "results": [
            {"scenario_id": "chain_tamper", "expected_outcome": None, "observed_outcome": None, "passed": True},
            {"scenario_id": "chain_tamper_blank", "expected_outcome": "", "observed_outcome": None, "passed": False},
            {
                "scenario_id": "concurrent_runs",
                "expected_outcome": "SUCCESS",
                "observed_outcome": "REFUSED+SUCCESS",
                "passed": True,
            },
            {"scenario_id": "happy_path", "expected_outcome": "SUCCESS", "observed_outcome": "SUCCESS", "passed": True},
            {
                "scenario_id": "stuck",
                "expected_outcome": "SUCCESS",
                "observed_outcome": "NONE+SUCCESS",
                "passed": False,
            },
        ],
    }
    assert client.post("/api/evals/results", json=run, headers=OPERATOR).status_code == 201
    proof = client.get("/api/proof").json()
    assert proof["outcomes"] == {"SUCCESS": 3, "PARTIAL": 0, "REFUSED": 1, "NEEDS_HUMAN": 0}
    assert {"scenario_id": "chain_tamper_blank", "explanation": "expected the detection to hold, observed None"} in (
        proof["named_failures"]
    )
    latest = {row["scenario_id"]: row for row in client.get("/api/evals/latest").json()["results"]}
    assert (
        latest["chain_tamper"]["expected_outcome"] is None and latest["chain_tamper_blank"]["expected_outcome"] is None
    )
    wrong = {"results": [{"scenario_id": "x", "expected_outcome": "MAYBE", "passed": True}]}
    assert client.post("/api/evals/results", json=wrong, headers=OPERATOR).status_code == 422


def test_the_sandbox_runs_a_scenario_then_cools_down(sandbox_client: tuple[TestClient, FakeStripe]) -> None:
    client, stripe = sandbox_client
    assert client.get("/api/sandbox/status").json() == {"available": True, "queue_depth": 0, "cooldown_seconds": 0}

    created = client.post("/api/sandbox/runs", json={"scenario": "happy_path"})
    assert created.status_code == 202
    body = created.json()
    assert body["sandbox_plan_key"] == "judge_pro" and body["approval_mode"] == "sandbox_auto"
    assert body["events_urls"] == [f"/api/runs/{run_id}/events" for run_id in body["run_ids"]]
    events = wait_for_outcome(client, body["run_ids"][0])
    assert events[-1]["payload"]["outcome"] == "SUCCESS"
    assert stripe.read_back(stripe.product_for("judge_pro")).value == Money(2500, "usd")
    assert stripe.read_back(stripe.product_for("pro")).value == Money(2000, "usd")

    busy = client.post("/api/sandbox/runs", json={"scenario": "happy_path"})
    assert busy.status_code == 429 and busy.json()["error"] == "rate_limited"
    assert busy.json()["retry_after"] > 0 and busy.headers["retry-after"] == str(busy.json()["retry_after"])
    status = client.get("/api/sandbox/status").json()
    assert status["available"] is False and status["cooldown_seconds"] > 0
    assert client.post("/api/sandbox/runs", json={"scenario": "delete_everything"}).status_code == 422


def test_the_sandbox_without_apps_answers_503_with_a_remedy(settings: Settings) -> None:
    AppStatus.should_exit_event = None
    with TestClient(create_app(settings, AdapterSet())) as client:
        response = client.post("/api/sandbox/runs", json={"scenario": "happy_path"})
        assert response.status_code == 503 and response.json()["remedy"]
        assert client.get("/api/sandbox/status").json()["available"] is False
        heal = client.post("/api/monitor/heal", json={"plan_key": "pro"}, headers=OPERATOR)
        assert heal.status_code == 503
