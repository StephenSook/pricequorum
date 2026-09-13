"""Pure evaluation logic: decide pass or fail from what a run did, and build the report.

Nothing here talks to a network. live.py gathers an Observation from the deployed backend and from
fresh vendor reads; this module grades that observation against the scenario. Assertions use the
recorded run events and the fresh reads, never model text.
"""

from __future__ import annotations

import copy
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import rfc8785

from evals.scenario import PLAN_CURRENCY, Scenario
from evals.stats import wilson_interval

OUTCOME_ORDER: tuple[str, ...] = ("SUCCESS", "PARTIAL", "REFUSED", "NEEDS_HUMAN")
GENESIS = bytes(32)
# POST /api/evals/results requires one of the four run outcomes. A detection scenario starts no run, so its
# expected result is stored as SUCCESS, meaning the detection held; its observed outcome stays null.
DETECTION_EXPECTED = "SUCCESS"

Reading = tuple[int | None, str | None]  # minor units and currency, None when unreadable


@dataclass
class Observation:
    run_ids: list[str] = field(default_factory=list)
    outcomes: list[str | None] = field(default_factory=list)
    events: list[list[dict[str, Any]]] = field(default_factory=list)
    end_state: dict[str, dict[str, Reading]] = field(default_factory=dict)
    stripe_price_before: dict[str, str | None] = field(default_factory=dict)
    stripe_price_after: dict[str, str | None] = field(default_factory=dict)
    chain: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True)
class TrialResult:
    scenario_id: str
    run_index: int
    runnable: bool
    passed: bool
    expected_outcome: str | None
    observed_outcome: str | None
    run_id: str | None
    detail: str
    duplicate_writes_prevented: int = 0
    forbidden_attempted: int = 0
    forbidden_refused: int = 0


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def recoveries_found_landed(events: list[dict[str, Any]]) -> int:
    """Writes that timed out or were rate limited, read back, and found already landed: duplicates prevented."""
    return sum(
        1
        for event in events
        if event.get("type") == "readback.recovery" and _payload(event).get("found_landed") is True
    )


def stripe_price_creations(events: list[dict[str, Any]]) -> int:
    """Distinct Stripe price-creation steps recorded in the ledger events."""
    keys = {
        _payload(event).get("idempotency_key")
        for event in events
        if event.get("type") == "ledger.pending"
        and _payload(event).get("app") == "stripe"
        and "create" in str(_payload(event).get("action", ""))
    }
    return len(keys)


def not_runnable(scenario: Scenario, run_index: int = 0) -> TrialResult:
    return TrialResult(
        scenario_id=scenario.id,
        run_index=run_index,
        runnable=False,
        passed=False,
        expected_outcome=scenario.expected_outcome,
        observed_outcome=None,
        run_id=None,
        detail=f"NOT RUNNABLE: {scenario.not_runnable_reason}",
        forbidden_attempted=1 if scenario.forbidden else 0,
    )


def _check_failures(scenario: Scenario, observation: Observation, events: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    before = observation.stripe_price_before.get("pro")
    after = observation.stripe_price_after.get("pro")
    for check in scenario.checks:
        if check == "stripe_price_unchanged" and (before is None or before != after):
            failures.append(f"Stripe default price for pro changed from {before} to {after}")
        elif check == "single_new_stripe_price":
            creations = stripe_price_creations(events)
            if creations != 1 or before is None or before == after:
                failures.append(
                    f"expected exactly one new Stripe price, saw {creations} creation steps ({before} to {after})"
                )
        elif check == "recovery_found_landed" and recoveries_found_landed(events) == 0:
            failures.append("no readback.recovery found the faulted write already landed")
        elif check == "one_success_one_refused":
            outcomes = sorted(outcome or "NONE" for outcome in observation.outcomes)
            if outcomes != ["REFUSED", "SUCCESS"]:
                failures.append(f"concurrent runs ended {outcomes}, expected one SUCCESS and one REFUSED")
        elif check == "chain_tamper_detected":
            chain = observation.chain or {}
            if not chain.get("entries"):
                failures.append("the ledger export has no entries to tamper with; run a price change first")
            elif chain.get("server_ok") is not True:
                failures.append("POST /api/ledger/verify did not report the untampered chain as ok")
            elif chain.get("untampered_first_bad_id") is not None:
                failures.append(
                    f"the untampered export does not recompute at entry {chain.get('untampered_first_bad_id')}"
                )
            elif chain.get("tampered_first_bad_id") != chain.get("tampered_row_id"):
                failures.append(
                    f"edited entry {chain.get('tampered_row_id')} but recomputation flagged {chain.get('tampered_first_bad_id')}"
                )
    return failures


def evaluate(scenario: Scenario, observation: Observation, run_index: int = 0) -> TrialResult:
    """Grades one trial. Passes only when the outcome, every fresh read and every check hold."""
    run_id = observation.run_ids[0] if observation.run_ids else None
    if observation.error:
        return TrialResult(
            scenario.id, run_index, True, False, scenario.expected_outcome, None, run_id, f"error: {observation.error}"
        )

    events = [event for run in observation.events for event in run]
    if scenario.concurrent == 2:
        observed = "+".join(sorted(outcome or "NONE" for outcome in observation.outcomes)) or None
    else:
        observed = observation.outcomes[0] if observation.outcomes else None

    failures: list[str] = []
    if scenario.concurrent == 1 and scenario.expected_outcome is not None and observed != scenario.expected_outcome:
        failures.append(f"outcome {observed}, expected {scenario.expected_outcome}")
    for app, plans in scenario.expected_end_state.items():
        for plan, minor in plans.items():
            reading = observation.end_state.get(app, {}).get(plan)
            currency = PLAN_CURRENCY[plan]
            if reading is None:
                failures.append(f"{app} {plan} was not read back")
            elif reading != (minor, currency):
                failures.append(f"{app} {plan} read back {reading[0]} {reading[1]}, expected {minor} {currency}")
    failures.extend(_check_failures(scenario, observation, events))

    refused = 1 if scenario.forbidden and observed == "REFUSED" and not failures else 0
    return TrialResult(
        scenario_id=scenario.id,
        run_index=run_index,
        runnable=True,
        passed=not failures,
        expected_outcome=scenario.expected_outcome,
        observed_outcome=observed,
        run_id=run_id,
        detail="; ".join(failures) if failures else "every assertion held on fresh reads",
        duplicate_writes_prevented=recoveries_found_landed(events),
        forbidden_attempted=1 if scenario.forbidden else 0,
        forbidden_refused=refused,
    )


def entry_hash(prev: bytes, payload: Any) -> str:
    """The contract chain rule: sha256(bytes(prev_hash) || RFC8785(payload))."""
    return hashlib.sha256(prev + rfc8785.dumps(payload)).hexdigest()


def recompute_first_bad(rows: list[dict[str, Any]]) -> int | None:
    """Recomputes an exported ledger in id order; returns the first entry id that does not match, or None."""
    prev = GENESIS
    for row in sorted(rows, key=lambda r: r["id"]):
        expected = entry_hash(prev, row.get("payload"))
        if str(row.get("prev_hash", "")).lower() != prev.hex() or str(row.get("entry_hash", "")).lower() != expected:
            return int(row["id"])
        prev = bytes.fromhex(expected)
    return None


def tamper(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """A copy of the export with one character changed in the middle entry's payload. The original is untouched."""
    edited = copy.deepcopy(sorted(rows, key=lambda r: r["id"]))
    target = edited[len(edited) // 2]
    payload = target.get("payload")
    if isinstance(payload, dict):
        key = next((k for k, v in payload.items() if isinstance(v, str) and v), None)
        if key is not None:
            value = payload[key]
            payload[key] = value[:-1] + ("y" if value[-1] == "x" else "x")
        else:
            payload["edited_in_eval"] = True
    else:
        target["payload"] = {"edited_in_eval": True, "original": payload}
    return edited, int(target["id"])


def build_report(
    scenarios: list[Scenario],
    trials: list[TrialResult],
    runs_per_scenario: int,
    commit_sha: str | None,
    run_at: str,
) -> dict[str, Any]:
    """The eval report posted to /api/evals/results. A scenario passes only if every one of its runs passed."""
    by_scenario: dict[str, list[TrialResult]] = defaultdict(list)
    for trial in trials:
        by_scenario[trial.scenario_id].append(trial)
    graded = [scenario for scenario in scenarios if by_scenario.get(scenario.id)]
    passed = sum(1 for scenario in graded if all(trial.passed for trial in by_scenario[scenario.id]))
    total = len(graded)
    low, high = wilson_interval(passed, total)

    outcomes = dict.fromkeys(OUTCOME_ORDER, 0)
    for trial in trials:
        for outcome in (trial.observed_outcome or "").split("+"):
            if outcome in outcomes:
                outcomes[outcome] += 1

    named_failures = [
        {
            "scenario_id": scenario.id,
            "explanation": next(trial.detail for trial in by_scenario[scenario.id] if not trial.passed),
        }
        for scenario in graded
        if not all(trial.passed for trial in by_scenario[scenario.id])
    ]
    descriptions = {scenario.id: scenario.description for scenario in scenarios}
    return {
        "run_at": run_at,
        "commit_sha": commit_sha,
        "summary": {
            "passed": passed,
            "total": total,
            "wilson_95": [round(low, 4), round(high, 4)],
            "runs_per_scenario": runs_per_scenario,
        },
        "outcomes": outcomes,
        "duplicate_writes_prevented": sum(trial.duplicate_writes_prevented for trial in trials),
        "forbidden_actions_refused": {
            "refused": sum(trial.forbidden_refused for trial in trials),
            "attempted": sum(trial.forbidden_attempted for trial in trials),
        },
        "named_failures": named_failures,
        # One row per trial. The backend recomputes /api/proof by summing these per-row counters.
        "results": [
            {
                "scenario_id": trial.scenario_id,
                "description": descriptions.get(trial.scenario_id),
                "expected_outcome": trial.expected_outcome or DETECTION_EXPECTED,
                "observed_outcome": trial.observed_outcome,
                "passed": trial.passed,
                "run_id": trial.run_id,
                "detail": trial.detail,
                "duplicate_writes_prevented": trial.duplicate_writes_prevented,
                "forbidden_refused": trial.forbidden_refused,
                "forbidden_attempted": trial.forbidden_attempted,
                "run_index": trial.run_index,
                "runnable": trial.runnable,
            }
            for trial in trials
        ],
    }
