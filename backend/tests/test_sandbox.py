"""The judge sandbox: every scenario runs against the sandbox plan only, and the limits hold."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from pricequorum import ledger
from pricequorum.adapters.faults import EnvFaultInjector
from pricequorum.adapters_factory import AdapterSet
from pricequorum.config import Settings
from pricequorum.monitor import DriftMonitor
from pricequorum.orchestrator import SANDBOX_APPROVER, Orchestrator
from pricequorum.ports import AdapterRefusal, Money
from pricequorum.sandbox import TAMPER_INVARIANTS, AirtableLockSetter, Sandbox, SandboxBusy, SandboxUnavailable
from tests.fakes import sandbox_world
from tests.runlog import ledger_steps, outcome, payloads, types

JUDGE = "judge_pro"
CLIENT = "203.0.113.7"


@pytest.fixture
def box(settings: Settings) -> SimpleNamespace:
    stripe, notion, airtable = sandbox_world()
    adapters = AdapterSet(stripe, notion, airtable, None)

    def with_fault(fault: str) -> AdapterSet:
        stripe.faults = EnvFaultInjector(fault)
        return AdapterSet(stripe, notion, airtable, None)

    orchestrator = Orchestrator(settings, adapters, adapters_for_fault=with_fault)
    monitor = DriftMonitor(adapters)
    relaxed = settings.model_copy(update={"pq_sandbox_cooldown_seconds": 0, "pq_sandbox_runs_per_minute": 100})
    sandbox = Sandbox(relaxed, orchestrator, monitor, airtable)
    return SimpleNamespace(stripe=stripe, notion=notion, airtable=airtable, monitor=monitor, sandbox=sandbox)


def play(box: SimpleNamespace, scenario: str) -> list[str]:
    job = box.sandbox.submit(scenario, CLIENT)
    assert box.sandbox.process_one(timeout=1)
    return job.run_ids


def assert_demo_plans_untouched(box: SimpleNamespace) -> None:
    for plan, amount in (
        ("pro", Money(2000, "usd")),
        ("pro_plus", Money(4900, "usd")),
        ("pro_eur", Money(1900, "eur")),
    ):
        assert box.stripe.read_back(box.stripe.product_for(plan)).value == amount
    assert box.notion.value_for("pro") == 20.0 and box.airtable.value_for("pro") == 20.0


def test_happy_path_changes_only_the_sandbox_plan_and_moves_on_each_time(box: SimpleNamespace) -> None:
    first = play(box, "happy_path")[0]
    assert outcome(first)["outcome"] == "SUCCESS"
    assert box.stripe.read_back(box.stripe.product_for(JUDGE)).value == Money(2500, "usd")
    assert box.notion.value_for(JUDGE) == 25.0 and box.airtable.value_for(JUDGE) == 25.0
    decided = payloads(first, "approval.decided")[0]
    assert (decided["mode"], decided["approver_display"]) == ("sandbox_auto", SANDBOX_APPROVER)

    second = play(box, "happy_path")[0]
    assert payloads(second, "policy.decided")[-1]["rule"] == "all_rules_passed"
    assert box.stripe.read_back(box.stripe.product_for(JUDGE)).value == Money(2600, "usd")
    assert_demo_plans_untouched(box)


def test_timeout_after_commit_recovers_the_landed_price(box: SimpleNamespace) -> None:
    run_id = play(box, "timeout_after_commit")[0]
    fault = payloads(run_id, "adapter.fault")[0]
    assert fault["injected"] is True and fault["call_site"] == "stripe.price.create"
    assert payloads(run_id, "readback.recovery")[0]["found_landed"] is True
    assert outcome(run_id)["outcome"] == "SUCCESS" and box.stripe.creates == 1
    assert_demo_plans_untouched(box)


def test_prompt_injection_is_refused_without_a_write(box: SimpleNamespace) -> None:
    run_id = play(box, "prompt_injection")[0]
    assert outcome(run_id)["outcome"] == "REFUSED"
    assert payloads(run_id, "policy.decided")[-1]["rule"] == "direction_rule"
    assert "ledger.pending" not in types(run_id) and box.stripe.creates == 0


def test_locked_record_is_refused_then_unlocked(box: SimpleNamespace) -> None:
    run_id = play(box, "locked_record")[0]
    assert outcome(run_id)["outcome"] == "REFUSED"
    assert payloads(run_id, "policy.decided")[-1]["rule"] == "locked_record"
    record = next(rid for rid, row in box.airtable.rows.items() if row["pq_plan_id"] == JUDGE)
    assert box.airtable.lock_calls == [(record, True), (record, False)]
    assert box.airtable.rows[record]["locked"] is False and box.stripe.creates == 0


def test_chain_tamper_detects_the_change_on_a_copy_and_leaves_the_ledger_alone(box: SimpleNamespace) -> None:
    play(box, "happy_path")
    before = ledger.export()["rows"]
    run_id = play(box, "chain_tamper")[0]

    result = outcome(run_id)
    assert result["outcome"] == "SUCCESS" and result["invariants_expected"] == list(TAMPER_INVARIANTS)
    checks = payloads(run_id, "invariant.result")
    assert [c["name"] for c in checks] == list(TAMPER_INVARIANTS) and all(c["ok"] for c in checks)
    middle = before[len(before) // 2]["id"]
    assert f"entry {middle}" in checks[1]["detail"]
    assert ledger.export()["rows"][: len(before)] == before
    assert ledger.verify()["ok"] is True


def test_chain_tamper_on_an_empty_ledger_asks_for_a_run_first(box: SimpleNamespace) -> None:
    run_id = play(box, "chain_tamper")[0]
    result = outcome(run_id)
    assert result["outcome"] == "NEEDS_HUMAN" and "happy_path" in result["remedy"]


def test_concurrent_runs_let_exactly_one_write(box: SimpleNamespace) -> None:
    box.stripe.delay = 0.3
    run_ids = play(box, "concurrent_runs")
    assert sorted(outcome(r)["outcome"] for r in run_ids) == ["REFUSED", "SUCCESS"]
    refused = next(r for r in run_ids if outcome(r)["outcome"] == "REFUSED")
    assert payloads(refused, "policy.decided")[-1]["rule"] == "concurrent_run"
    assert box.stripe.creates == 1


def test_drift_is_detected_healed_through_the_ledger_and_confirmed(box: SimpleNamespace) -> None:
    run_id = play(box, "drift")[0]

    published = box.monitor.events_after(0)
    detected = next(e["payload"] for e in published if e["type"] == "drift.detected")
    assert (detected["plan_key"], detected["app"]) == (JUDGE, "notion")
    assert detected["expected"] == {"minor_units": 2000, "currency": "usd"}
    assert detected["observed"] == {"minor_units": 2300, "currency": "usd"} and detected["raw_value"] == "23.0"

    assert outcome(run_id)["outcome"] == "SUCCESS"
    assert payloads(run_id, "policy.decided")[-1]["rule"] == "heal_derived"
    assert ledger_steps(run_id) == [("notion", "update_price")] and box.stripe.creates == 0
    healed = next(e["payload"] for e in published if e["type"] == "drift.healed")
    assert healed == {"plan_key": JUDGE, "app": "notion", "run_id": run_id}
    assert published[-1]["type"] == "monitor.ok" and box.notion.value_for(JUDGE) == 20.0
    assert_demo_plans_untouched(box)


def test_a_scoped_run_that_names_another_plan_is_refused(box: SimpleNamespace, settings: Settings) -> None:
    orchestrator = box.sandbox.orchestrator
    run_id = orchestrator.create_run("Set Pro to $25/month", approval_mode="sandbox_auto", plan_scope=JUDGE)
    orchestrator.execute(run_id)
    assert outcome(run_id)["outcome"] == "REFUSED"
    assert payloads(run_id, "policy.decided")[-1]["rule"] == "sandbox_plan_scope"
    assert box.stripe.creates == 0
    assert_demo_plans_untouched(box)


def test_limits_per_address_cooldown_and_queue(box: SimpleNamespace, settings: Settings) -> None:
    now = [1000.0]
    strict = settings.model_copy(
        update={"pq_sandbox_cooldown_seconds": 30, "pq_sandbox_runs_per_minute": 2, "pq_sandbox_max_queue": 2}
    )
    sandbox = Sandbox(strict, box.sandbox.orchestrator, box.monitor, box.airtable, clock=lambda: now[0])

    sandbox.submit("prompt_injection", CLIENT)
    with pytest.raises(SandboxBusy) as cooling:
        sandbox.submit("prompt_injection", "198.51.100.1")
    assert cooling.value.retry_after == 30
    assert sandbox.status() == {"available": False, "queue_depth": 1, "cooldown_seconds": 30}

    now[0] += 31
    sandbox.submit("prompt_injection", CLIENT)
    now[0] += 31
    with pytest.raises(SandboxBusy) as queue_full:
        sandbox.submit("prompt_injection", "198.51.100.1")
    assert "queue" in queue_full.value.detail

    assert sandbox.process_one(timeout=1) and sandbox.process_one(timeout=1)
    assert sandbox.status()["queue_depth"] == 0

    # The per-address limit counts within one minute; the cooldown is off here so only that limit applies.
    clock = [5000.0]
    open_queue = strict.model_copy(update={"pq_sandbox_cooldown_seconds": 0, "pq_sandbox_max_queue": 10})
    limited = Sandbox(open_queue, box.sandbox.orchestrator, box.monitor, box.airtable, clock=lambda: clock[0])
    limited.submit("prompt_injection", CLIENT)
    clock[0] += 10
    limited.submit("prompt_injection", CLIENT)
    with pytest.raises(SandboxBusy) as per_address:
        limited.submit("prompt_injection", CLIENT)
    assert "address" in per_address.value.detail and per_address.value.retry_after == 50
    limited.submit("prompt_injection", "198.51.100.1")
    clock[0] += 51
    limited.submit("prompt_injection", CLIENT)
    while limited.process_one(timeout=0.1):
        pass


def test_without_apps_the_sandbox_is_unavailable(settings: Settings) -> None:
    orchestrator = Orchestrator(settings, AdapterSet())
    sandbox = Sandbox(settings, orchestrator, DriftMonitor(AdapterSet()), None)
    with pytest.raises(SandboxUnavailable) as unavailable:
        sandbox.submit("happy_path", CLIENT)
    assert unavailable.value.remedy and sandbox.status()["available"] is False


def test_a_demo_plan_can_never_be_the_sandbox_plan() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, pq_sandbox_plan_key="pro")  # type: ignore[call-arg]


def test_the_airtable_lock_setter_patches_only_the_locked_checkbox() -> None:
    seen: list[tuple[str, str, object]] = []

    def accept(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"id": "recJudge", "fields": {"Locked": True}})

    AirtableLockSetter(
        "pat", "appBase", "Plans", client=httpx.Client(transport=httpx.MockTransport(accept))
    ).set_locked("recJudge", True)
    assert seen == [("PATCH", "/v0/appBase/Plans/recJudge", {"fields": {"Locked": True}})]

    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"type": "INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND"}})

    setter = AirtableLockSetter("pat", "appBase", "Plans", client=httpx.Client(transport=httpx.MockTransport(refuse)))
    with pytest.raises(AdapterRefusal) as refused:
        setter.set_locked("recJudge", False)
    assert "Locked checkbox" in refused.value.remedy
