"""The run loop against in-memory apps: the event order, the exactly-once writes, fault recovery,
refusals, concurrency, approvals and crash recovery."""

from __future__ import annotations

import threading
import time
from typing import Any

from pricequorum import approvals, db, ledger
from pricequorum.adapters.faults import EnvFaultInjector
from pricequorum.adapters_factory import AdapterSet
from pricequorum.config import Settings
from pricequorum.events import list_events
from pricequorum.orchestrator import Orchestrator
from pricequorum.ports import Money
from pricequorum.verifier import INVARIANTS_EXPECTED
from tests.fakes import FakeApproval, world


def types(run_id: str) -> list[str]:
    return [event["type"] for event in list_events(run_id)]


def payloads(run_id: str, type_name: str) -> list[dict[str, Any]]:
    return [event["payload"] for event in list_events(run_id) if event["type"] == type_name]


def outcome(run_id: str) -> dict[str, Any]:
    return payloads(run_id, "run.outcome")[-1]


def run_now(orchestrator: Orchestrator, text: str, **kwargs: Any) -> str:
    run_id = orchestrator.create_run(text, **kwargs)
    orchestrator.execute(run_id)
    return run_id


def test_happy_path_writes_each_app_once_and_proves_it(settings: Settings) -> None:
    stripe, notion, airtable = world()
    orchestrator = Orchestrator(settings, AdapterSet(stripe, notion, airtable, FakeApproval()))
    run_id = run_now(orchestrator, "raise Pro to $25/month", approval_mode="sandbox_auto")

    result = outcome(run_id)
    assert result["outcome"] == "SUCCESS"
    assert result["invariants_expected"] == list(INVARIANTS_EXPECTED)
    assert len(result["chain_head"]) == 64 and len(result["signature"]) == 128 and len(result["public_key"]) == 64

    order = types(run_id)
    assert order[:4] == ["run.created", "intent.parsed", "resolve.completed", "policy.decided"]
    assert order.index("approval.requested") < order.index("approval.decided") < order.index("ledger.pending")
    assert order[-1] == "run.outcome"
    assert [p["name"] for p in payloads(run_id, "invariant.result")] == list(INVARIANTS_EXPECTED)
    assert all(p["ok"] for p in payloads(run_id, "invariant.result"))
    assert payloads(run_id, "approval.decided")[0]["approver_display"] == "sandbox auto-approver"

    product = stripe.product_for("pro")
    assert stripe.read_back(product).value == Money(2500, "usd")
    assert stripe.active_prices(product) == [stripe.products[product]["default_price"]]
    assert notion.value_for("pro") == 25.0 and airtable.value_for("pro") == 25.0
    assert notion.value_for("pro_plus") == 49.0 and stripe.read_back(stripe.product_for("pro_eur")).value == Money(
        1900, "eur"
    )
    readbacks = payloads(run_id, "readback.result")
    assert {r["app"] for r in readbacks} == {"stripe", "notion", "airtable"}
    assert all(r["fresh"] and r["value"] == {"minor_units": 2500, "currency": "usd"} for r in readbacks)
    assert ledger.verify()["ok"] is True


def test_timeout_after_commit_reads_back_and_never_writes_twice(settings: Settings) -> None:
    stripe, notion, airtable = world(stripe_faults=EnvFaultInjector("timeout_after_commit"))
    orchestrator = Orchestrator(settings, AdapterSet(stripe, notion, airtable, None))
    run_id = run_now(orchestrator, "raise Pro to $25/month", approval_mode="sandbox_auto")

    fault = payloads(run_id, "adapter.fault")[0]
    assert (fault["call_site"], fault["kind"], fault["injected"]) == ("stripe.price.create", "timeout", True)
    recovery = payloads(run_id, "readback.recovery")[0]
    assert recovery["found_landed"] is True and recovery["external_object_id"]
    assert stripe.creates == 1
    assert outcome(run_id)["outcome"] == "SUCCESS"


def test_a_derived_write_that_never_lands_is_partial_and_named(settings: Settings) -> None:
    stripe, notion, airtable = world(notion_fail=True)
    orchestrator = Orchestrator(settings, AdapterSet(stripe, notion, airtable, None))
    run_id = run_now(orchestrator, "raise Pro to $25/month", approval_mode="sandbox_auto")

    result = outcome(run_id)
    assert result["outcome"] == "PARTIAL"
    assert "Notion" in (result["remedy"] or "")
    agree = next(p for p in payloads(run_id, "invariant.result") if p["name"] == "all_three_surfaces_agree")
    assert agree["ok"] is False
    with db.connect() as conn:
        states = {
            row["action"]: row["state"]
            for row in conn.execute("select action, state from action_ledger where run_id = %s", (run_id,))
        }
    assert states["update_price"] == "failed" and states["create_price"] == "completed"


def test_a_locked_record_is_refused_before_anything_is_written(settings: Settings) -> None:
    stripe, notion, airtable = world(airtable_locked=True)
    orchestrator = Orchestrator(settings, AdapterSet(stripe, notion, airtable, None))
    run_id = run_now(orchestrator, "raise Pro to $25/month", approval_mode="sandbox_auto")

    result = outcome(run_id)
    assert result["outcome"] == "REFUSED" and "Locked" in result["remedy"]
    assert stripe.creates == 0 and "ledger.pending" not in types(run_id)


def test_a_second_run_on_a_locked_plan_is_refused_cleanly(settings: Settings) -> None:
    stripe, notion, airtable = world()
    orchestrator = Orchestrator(settings, AdapterSet(stripe, notion, airtable, None))
    holder = db.dedicated()
    try:
        holder.execute("select pg_advisory_lock(hashtext('plan:pro:usd'))")
        run_id = run_now(orchestrator, "raise Pro to $25/month", approval_mode="sandbox_auto")
    finally:
        holder.execute("select pg_advisory_unlock(hashtext('plan:pro:usd'))")
        holder.close()
    assert outcome(run_id)["outcome"] == "REFUSED"
    assert payloads(run_id, "policy.decided")[-1]["rule"] == "concurrent_run"
    assert stripe.creates == 0


def _wait_for_approval_row(run_id: str) -> None:
    deadline = time.monotonic() + 10
    while approvals.get(run_id) is None and time.monotonic() < deadline:
        time.sleep(0.02)


def test_an_operator_denial_refuses_the_change(settings: Settings) -> None:
    stripe, notion, airtable = world()
    orchestrator = Orchestrator(settings, AdapterSet(stripe, notion, airtable, None))
    run_id = orchestrator.create_run("raise Pro to $25/month")
    worker = threading.Thread(target=orchestrator.execute, args=(run_id,))
    worker.start()
    _wait_for_approval_row(run_id)
    assert approvals.decide(run_id, "deny", "Stephen") == "DENIED"
    assert approvals.decide(run_id, "approve", "Someone else") == "ALREADY_DECIDED"
    worker.join(10)
    assert outcome(run_id)["outcome"] == "REFUSED"
    assert payloads(run_id, "approval.requested")[0]["mode"] == "operator"
    assert stripe.creates == 0


def test_slack_approval_is_posted_bound_to_the_args_and_updated(settings: Settings) -> None:
    stripe, notion, airtable = world()
    slack = FakeApproval()
    orchestrator = Orchestrator(settings, AdapterSet(stripe, notion, airtable, slack))
    run_id = orchestrator.create_run("raise Pro to $25/month")
    worker = threading.Thread(target=orchestrator.execute, args=(run_id,))
    worker.start()
    _wait_for_approval_row(run_id)
    row = approvals.get(run_id)
    assert row is not None
    assert approvals.decide(run_id, "approve", "Stephen", "0" * 64) == "ARGS_MISMATCH"
    assert approvals.decide(run_id, "approve", "Stephen", row["args_hash"]) == "APPROVED"
    worker.join(10)
    assert outcome(run_id)["outcome"] == "SUCCESS"
    requested = payloads(run_id, "approval.requested")[0]
    assert (requested["mode"], requested["slack_channel"]) == ("slack", "C0TEST")
    assert slack.outcomes and slack.outcomes[0][1] == "APPROVED"


def test_an_approval_nobody_gives_expires(settings: Settings) -> None:
    stripe, notion, airtable = world()
    orchestrator = Orchestrator(
        settings.model_copy(update={"pq_approval_ttl_seconds": 0}), AdapterSet(stripe, notion, airtable, None)
    )
    run_id = run_now(orchestrator, "raise Pro to $25/month")
    assert outcome(run_id)["outcome"] == "NEEDS_HUMAN"
    assert approvals.get(run_id)["status"] == "EXPIRED"  # type: ignore[index]
    assert stripe.creates == 0


def test_repeating_a_completed_change_writes_nothing(settings: Settings) -> None:
    stripe, notion, airtable = world()
    orchestrator = Orchestrator(settings, AdapterSet(stripe, notion, airtable, None))
    run_now(orchestrator, "raise Pro to $25/month", approval_mode="sandbox_auto")
    again = run_now(orchestrator, "raise Pro to $25/month", approval_mode="sandbox_auto")
    assert outcome(again)["outcome"] == "SUCCESS"
    assert payloads(again, "policy.decided")[-1]["rule"] == "already_in_effect"
    assert stripe.creates == 1 and "ledger.pending" not in types(again)


def test_requests_that_cannot_proceed_end_with_a_remedy(settings: Settings) -> None:
    stripe, notion, airtable = world()
    orchestrator = Orchestrator(settings, AdapterSet(stripe, notion, airtable, None))
    unparsed = run_now(orchestrator, "make it cheaper please")
    edit = run_now(orchestrator, "Just edit the amount in place")
    sync = run_now(orchestrator, "Sync Pro from Notion")
    unconfigured = run_now(Orchestrator(settings, AdapterSet()), "raise Pro to $25/month")
    assert [outcome(r)["outcome"] for r in (unparsed, edit, sync, unconfigured)] == [
        "NEEDS_HUMAN",
        "REFUSED",
        "REFUSED",
        "NEEDS_HUMAN",
    ]
    assert all(outcome(r)["remedy"] for r in (unparsed, edit, sync, unconfigured))
    assert outcome(unconfigured)["invariants_expected"] == []
    assert stripe.creates == 0


def test_recovery_ends_runs_a_previous_process_left_open(settings: Settings) -> None:
    orchestrator = Orchestrator(settings, AdapterSet())
    run_id = orchestrator.create_run("raise Pro to $25/month")
    ledger.pending(run_id, 1, "stripe", "create_price", "pq:pro:usd-month-2500:create_price", {"a": 1}, {})
    assert orchestrator.recover_interrupted() == 1
    assert outcome(run_id)["outcome"] == "PARTIAL"
    with db.connect() as conn:
        state = conn.execute("select state from action_ledger where run_id = %s", (run_id,)).fetchone()
    assert state is not None and state["state"] == "failed"
