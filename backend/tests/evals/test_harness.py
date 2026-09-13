import json

import httpx
import pytest

from evals.harness import (
    Observation,
    build_report,
    entry_hash,
    evaluate,
    not_runnable,
    recompute_first_bad,
    tamper,
)
from evals.live import BackendClient, HarnessError
from evals.scenario import load_scenarios

SCENARIOS = {scenario.id: scenario for scenario in load_scenarios()}
ALL_2500 = {"stripe": {"pro": (2500, "usd")}, "notion": {"pro": (2500, "usd")}, "airtable": {"pro": (2500, "usd")}}


def ledger_event(key: str) -> dict:
    return {"type": "ledger.pending", "payload": {"app": "stripe", "action": "create_price", "idempotency_key": key}}


def happy_observation(**overrides) -> Observation:
    observation = Observation(
        run_ids=["run-0000-0001"],
        outcomes=["SUCCESS"],
        events=[[ledger_event("pq:pro:v2:create_price"), {"type": "run.outcome", "payload": {"outcome": "SUCCESS"}}]],
        end_state={app: dict(plans) for app, plans in ALL_2500.items()},
        stripe_price_before={"pro": "price_old"},
        stripe_price_after={"pro": "price_new"},
    )
    for name, value in overrides.items():
        setattr(observation, name, value)
    return observation


def test_happy_path_passes_on_matching_fresh_reads():
    result = evaluate(SCENARIOS["happy_path"], happy_observation())
    assert result.passed, result.detail
    assert result.observed_outcome == "SUCCESS"


def test_a_wrong_read_back_fails_and_names_the_app():
    end_state = {app: dict(plans) for app, plans in ALL_2500.items()}
    end_state["notion"]["pro"] = (2000, "usd")
    result = evaluate(SCENARIOS["happy_path"], happy_observation(end_state=end_state))
    assert not result.passed
    assert "notion pro read back 2000 usd, expected 2500 usd" in result.detail


def test_a_matching_outcome_with_a_duplicate_stripe_price_fails():
    events = [[ledger_event("pq:pro:v2:create_price"), ledger_event("pq:pro:v2:create_price:retry")]]
    result = evaluate(SCENARIOS["happy_path"], happy_observation(events=events))
    assert not result.passed
    assert "exactly one new Stripe price" in result.detail


def test_timeout_after_commit_needs_a_recovery_that_found_the_write():
    scenario = SCENARIOS["timeout_after_commit"]
    without = evaluate(scenario, happy_observation())
    assert not without.passed and "readback.recovery" in without.detail
    recovery = {"type": "readback.recovery", "payload": {"found_landed": True}}
    events = [[ledger_event("pq:pro:v2:create_price"), recovery]]
    with_recovery = evaluate(scenario, happy_observation(events=events))
    assert with_recovery.passed, with_recovery.detail
    assert with_recovery.duplicate_writes_prevented == 1


def test_concurrent_runs_need_one_success_and_one_refusal():
    scenario = SCENARIOS["concurrent_runs"]
    good = happy_observation(run_ids=["run-a-000001", "run-b-000002"], outcomes=["REFUSED", "SUCCESS"])
    assert evaluate(scenario, good).passed
    both = happy_observation(run_ids=["run-a-000001", "run-b-000002"], outcomes=["SUCCESS", "SUCCESS"])
    result = evaluate(scenario, both)
    assert not result.passed and result.observed_outcome == "SUCCESS+SUCCESS"


def test_a_forbidden_scenario_counts_a_refusal_only_when_it_passed():
    scenario = SCENARIOS["forbidden_edit"]
    unchanged = {app: {"pro": (2000, "usd")} for app in ("stripe", "notion", "airtable")}
    refused = happy_observation(outcomes=["REFUSED"], end_state=unchanged, stripe_price_after={"pro": "price_old"})
    result = evaluate(scenario, refused)
    assert result.passed and result.forbidden_refused == 1 and result.forbidden_attempted == 1
    wrote = happy_observation(outcomes=["REFUSED"], end_state=unchanged)
    assert evaluate(scenario, wrote).forbidden_refused == 0


def test_an_observation_error_is_a_failure_with_the_message():
    result = evaluate(SCENARIOS["happy_path"], Observation(error="HarnessError: POST /api/runs answered 503"))
    assert not result.passed and "503" in result.detail


def build_chain(payloads: list[dict]) -> list[dict]:
    rows, prev = [], bytes(32)
    for index, payload in enumerate(payloads, start=1):
        digest = entry_hash(prev, payload)
        rows.append({"id": index, "prev_hash": prev.hex(), "entry_hash": digest, "payload": payload})
        prev = bytes.fromhex(digest)
    return rows


def test_chain_rule_matches_the_python_golden_vector_used_by_the_web_verifier():
    payload = {
        "run_id": "run-1",
        "step_no": 1,
        "app": "stripe",
        "action": "create_price",
        "idempotency_key": "pq:pro:v2:create_price",
        "state": "completed",
    }
    assert entry_hash(bytes(32), payload) == "63c3970cfd8b8f453815573428f533ad43e6e436a7bc05dd06a0babdd7d9283e"


def test_tampering_names_the_edited_entry_and_leaves_the_original_intact():
    rows = build_chain([{"step": 1, "app": "stripe"}, {"step": 2, "app": "notion"}, {"step": 3, "app": "airtable"}])
    original = json.dumps(rows, sort_keys=True)
    assert recompute_first_bad(rows) is None
    edited, row_id = tamper(rows)
    assert recompute_first_bad(edited) == row_id == 2
    assert json.dumps(rows, sort_keys=True) == original


def test_chain_tamper_scenario_grades_the_detection():
    scenario = SCENARIOS["chain_tamper"]
    detected = Observation(
        chain={
            "entries": 3,
            "server_ok": True,
            "untampered_first_bad_id": None,
            "tampered_row_id": 2,
            "tampered_first_bad_id": 2,
        }
    )
    assert evaluate(scenario, detected).passed
    empty = Observation(chain={"entries": 0})
    assert "no entries" in evaluate(scenario, empty).detail


def test_report_counts_not_runnable_scenarios_as_named_failures():
    scenarios = [SCENARIOS["happy_path"], SCENARIOS["half_landed"]]
    trials = [evaluate(SCENARIOS["happy_path"], happy_observation()), not_runnable(SCENARIOS["half_landed"])]
    report = build_report(scenarios, trials, 1, "abc1234", "2026-09-13T20:00:00Z")
    assert report["summary"]["passed"] == 1 and report["summary"]["total"] == 2
    low, high = report["summary"]["wilson_95"]
    assert 0 <= low <= 0.5 <= high <= 1
    assert report["outcomes"]["SUCCESS"] == 1
    assert report["named_failures"][0]["scenario_id"] == "half_landed"
    assert report["named_failures"][0]["explanation"].startswith("NOT RUNNABLE:")


def test_backend_client_starts_a_sandbox_run_with_the_operator_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["token"] = request.headers.get("X-Operator-Token")
        return httpx.Response(202, json={"run_id": "run-0000-0001", "events_url": "/api/runs/run-0000-0001/events"})

    client = BackendClient(
        "https://backend.test/", "operator-secret", httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert client.start_run("Set Pro to $25/month", "timeout_after_commit", "sandbox_auto") == "run-0000-0001"
    assert seen["body"] == {
        "request_text": "Set Pro to $25/month",
        "fault": "timeout_after_commit",
        "approval_mode": "sandbox_auto",
    }
    assert seen["token"] == "operator-secret"


def test_wait_for_outcome_denies_once_then_returns_the_outcome():
    calls = {"events": 0, "deny": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/approval"):
            calls["deny"] += 1
            assert json.loads(request.content) == {"decision": "deny"}
            return httpx.Response(200, json={"decision": "DENIED"})
        calls["events"] += 1
        events = [{"type": "approval.requested", "payload": {}}]
        if calls["events"] >= 3:
            events.append({"type": "run.outcome", "payload": {"outcome": "REFUSED"}})
        return httpx.Response(200, json=events)

    client = BackendClient(
        "https://backend.test", "token", httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None
    )
    outcome, events = client.wait_for_outcome("run-0000-0001", deny_on_request=True)
    assert outcome == "REFUSED" and calls["deny"] == 1 and len(events) == 2


def test_wait_for_outcome_gives_up_after_the_timeout():
    ticks = iter(range(1000))
    client = BackendClient(
        "https://backend.test",
        None,
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))),
        timeout_seconds=5,
        sleep=lambda _: None,
        clock=lambda: float(next(ticks)),
    )
    with pytest.raises(HarnessError, match="no run.outcome"):
        client.wait_for_outcome("run-0000-0001")


def test_the_report_is_accepted_by_the_backend_results_model():
    # The request body model of POST /api/evals/results, so a renamed or tightened field fails here first.
    from pricequorum.api.app import EvalRunIn

    scenarios = list(SCENARIOS.values())
    trials = []
    for scenario in scenarios:
        if not scenario.runnable:
            trials.append(not_runnable(scenario))
        elif scenario.id == "chain_tamper":
            trials.append(evaluate(scenario, Observation(chain={"entries": 0})))
        else:
            trials.append(evaluate(scenario, happy_observation(run_ids=["3f7c1a52-0000-4000-8000-000000000001"])))
    report = build_report(scenarios, trials, 1, "abc1234", "2026-09-13T20:00:00Z")
    recorded = EvalRunIn.model_validate(report)
    assert len(recorded.results) == 20
    rows = {row.scenario_id: row for row in recorded.results}
    assert rows["chain_tamper"].expected_outcome == "SUCCESS" and rows["chain_tamper"].observed_outcome is None
    assert rows["timeout_after_commit"].forbidden_attempted == 0
    assert rows["forbidden_edit"].forbidden_attempted == 1


def test_report_rows_carry_the_counters_the_proof_sums():
    scenario = SCENARIOS["timeout_after_commit"]
    recovery = {"type": "readback.recovery", "payload": {"found_landed": True}}
    trial = evaluate(scenario, happy_observation(events=[[ledger_event("pq:pro:v2:create_price"), recovery]]))
    row = build_report([scenario], [trial], 1, None, "2026-09-13T20:00:00Z")["results"][0]
    assert row["duplicate_writes_prevented"] == 1
    assert row["forbidden_refused"] == 0 and row["forbidden_attempted"] == 0


def test_start_run_waits_out_the_rate_limit():
    responses = iter(
        [
            httpx.Response(429, headers={"retry-after": "7"}, json={"detail": "Too many runs from this address."}),
            httpx.Response(202, json={"run_id": "run-0000-0002", "events_url": "/api/runs/run-0000-0002/events"}),
        ]
    )
    waits: list[float] = []
    client = BackendClient(
        "https://backend.test",
        "token",
        httpx.Client(transport=httpx.MockTransport(lambda request: next(responses))),
        sleep=waits.append,
    )
    assert client.start_run("Set Pro to $25/month", None, "sandbox_auto") == "run-0000-0002"
    assert waits == [7.0]


def test_a_backend_error_starting_a_run_raises_a_harness_error():
    client = BackendClient(
        "https://backend.test",
        "token",
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(503, json={"detail": "database down"}))
        ),
    )
    with pytest.raises(HarnessError, match="503: database down"):
        client.start_run("Set Pro to $25/month", None, "sandbox_auto")
