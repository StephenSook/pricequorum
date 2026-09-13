"""Evaluation scenario files: loading and schema validation.

One JSON file per scenario in evals/scenarios/. A scenario that cannot run against the current API
says so in not_runnable_reason. It is reported as a failure, never skipped silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"

# The scenario matrix of the master specification, in its order.
REQUIRED_IDS: tuple[str, ...] = (
    "happy_path",
    "idempotent_noop",
    "ambiguous_name",
    "no_conflate",
    "two_currency",
    "half_landed",
    "timeout_after_commit",
    "archived_referenced",
    "forbidden_edit",
    "migrate_needs_approval",
    "approval_denied",
    "approval_expired",
    "prompt_injection",
    "locked_record",
    "stale_read",
    "rate_limit_429",
    "concurrent_runs",
    "idempotency_409",
    "float_precision",
    "chain_tamper",
)
OUTCOMES = frozenset({"SUCCESS", "PARTIAL", "REFUSED", "NEEDS_HUMAN"})
APPS: tuple[str, ...] = ("stripe", "notion", "airtable")
# The seeded demo plans (scripts/seed.py) and the currency each one is priced in.
PLAN_CURRENCY: dict[str, str] = {"pro": "usd", "pro_plus": "usd", "pro_eur": "eur"}
APPROVALS = frozenset({"sandbox_auto", "operator_deny", "none"})
CHECKS = frozenset(
    {
        "stripe_price_unchanged",
        "single_new_stripe_price",
        "recovery_found_landed",
        "one_success_one_refused",
        "chain_tamper_detected",
    }
)
SETUP_ACTIONS = frozenset({"set_price", "set_raw_notion_price", "lock", "duplicate_stripe_product"})
# Fault names understood by pricequorum/adapters/faults.py.
FAULTS = frozenset(
    {
        "timeout_after_commit",
        "idempotency_409",
        "stripe_5xx",
        "half_landed",
        "server_5xx",
        "rate_limit",
        "rate_limit_429",
    }
)


class ScenarioError(ValueError):
    """The scenario files do not match the schema."""


@dataclass(frozen=True)
class Scenario:
    id: str
    description: str
    runnable: bool
    not_runnable_reason: str | None
    adapted_from_spec: str | None
    request_text: str | None
    fault: str | None
    approval: str
    concurrent: int
    setup: tuple[dict[str, Any], ...]
    expected_outcome: str | None
    expected_end_state: dict[str, dict[str, int]]
    checks: tuple[str, ...]
    forbidden: bool


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _setup_problems(actions: object) -> list[str]:
    if not isinstance(actions, list):
        return ["setup must be a list"]
    problems: list[str] = []
    for index, action in enumerate(actions):
        where = f"setup[{index}]"
        if not isinstance(action, dict) or action.get("action") not in SETUP_ACTIONS:
            problems.append(f"{where}: action must be one of {sorted(SETUP_ACTIONS)}")
            continue
        kind, plan = action["action"], action.get("plan")
        if plan not in PLAN_CURRENCY:
            problems.append(f"{where}: plan must be one of {sorted(PLAN_CURRENCY)}")
        if kind == "set_price" and (action.get("app") not in APPS or not _is_int(action.get("minor_units"))):
            problems.append(f"{where}: set_price needs app in {list(APPS)} and integer minor_units")
        if kind == "set_raw_notion_price" and not isinstance(action.get("value"), int | float):
            problems.append(f"{where}: set_raw_notion_price needs a numeric value as Notion would store it")
        if kind == "lock" and action.get("app") not in ("notion", "airtable"):
            problems.append(f"{where}: lock needs app notion or airtable")
        if kind == "duplicate_stripe_product" and not _nonblank(action.get("name")):
            problems.append(f"{where}: duplicate_stripe_product needs a name")
    return problems


def problems_in(data: object, filename: str) -> list[str]:
    """Every way one decoded scenario file breaks the schema. An empty list means it is valid."""
    if not isinstance(data, dict):
        return [f"{filename}: not a JSON object"]
    problems: list[str] = []
    scenario_id = data.get("id")
    if scenario_id not in REQUIRED_IDS:
        problems.append(f"id {scenario_id!r} is not one of the 20 scenario ids")
    elif filename != f"{scenario_id}.json":
        problems.append(f"file name must be {scenario_id}.json")
    if not _nonblank(data.get("description")):
        problems.append("description is required")

    runnable = data.get("runnable")
    reason = data.get("not_runnable_reason")
    if not isinstance(runnable, bool):
        problems.append("runnable must be true or false")
    elif runnable is False and not _nonblank(reason):
        problems.append("a scenario that is not runnable must state not_runnable_reason")
    elif runnable is True and reason is not None:
        problems.append("a runnable scenario must have not_runnable_reason null")
    if data.get("adapted_from_spec") is not None and not _nonblank(data.get("adapted_from_spec")):
        problems.append("adapted_from_spec must be null or explain the adaptation")

    approval = data.get("approval")
    if approval not in APPROVALS:
        problems.append(f"approval must be one of {sorted(APPROVALS)}")
    concurrent = data.get("concurrent")
    if concurrent not in (1, 2):
        problems.append("concurrent must be 1 or 2")
    request_text = data.get("request_text")
    if approval == "none":
        if request_text is not None:
            problems.append("a scenario without a run must have request_text null")
    elif not _nonblank(request_text):
        problems.append("request_text is required when the scenario starts a run")
    fault = data.get("fault")
    if fault is not None and fault not in FAULTS:
        problems.append(f"fault must be null or one of {sorted(FAULTS)}")

    expected_outcome = data.get("expected_outcome")
    if expected_outcome is not None and expected_outcome not in OUTCOMES:
        problems.append(f"expected_outcome must be null or one of {sorted(OUTCOMES)}")
    if runnable is True and approval != "none" and expected_outcome is None:
        problems.append("a runnable scenario that starts a run needs expected_outcome")

    end_state = data.get("expected_end_state")
    if not isinstance(end_state, dict):
        problems.append("expected_end_state must be an object of app to plan to minor units")
    else:
        for app, plans in end_state.items():
            if app not in APPS or not isinstance(plans, dict):
                problems.append(f"expected_end_state: unknown app {app!r}")
                continue
            for plan, minor in plans.items():
                if plan not in PLAN_CURRENCY or not _is_int(minor):
                    problems.append(f"expected_end_state.{app}.{plan} must be a known plan with integer minor units")

    checks = data.get("checks")
    if not isinstance(checks, list) or any(check not in CHECKS for check in checks):
        problems.append(f"checks must be a list drawn from {sorted(CHECKS)}")
    elif concurrent == 2 and "one_success_one_refused" not in checks:
        problems.append("a concurrent scenario must check one_success_one_refused")
    if not isinstance(data.get("forbidden"), bool):
        problems.append("forbidden must be true or false")
    problems.extend(_setup_problems(data.get("setup")))
    return [f"{filename}: {problem}" for problem in problems]


def _scenario_from(data: dict[str, Any]) -> Scenario:
    return Scenario(
        id=data["id"],
        description=data["description"],
        runnable=data["runnable"],
        not_runnable_reason=data["not_runnable_reason"],
        adapted_from_spec=data.get("adapted_from_spec"),
        request_text=data["request_text"],
        fault=data["fault"],
        approval=data["approval"],
        concurrent=data["concurrent"],
        setup=tuple(data["setup"]),
        expected_outcome=data["expected_outcome"],
        expected_end_state=data["expected_end_state"],
        checks=tuple(data["checks"]),
        forbidden=data["forbidden"],
    )


def load_scenarios(directory: Path = SCENARIO_DIR) -> list[Scenario]:
    """Loads all 20 scenarios in matrix order, or raises ScenarioError listing every problem."""
    problems: list[str] = []
    found: dict[str, Scenario] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            problems.append(f"{path.name}: invalid JSON ({error.msg} at line {error.lineno})")
            continue
        file_problems = problems_in(data, path.name)
        if file_problems:
            problems.extend(file_problems)
            continue
        found[data["id"]] = _scenario_from(data)
    missing = [scenario_id for scenario_id in REQUIRED_IDS if scenario_id not in found]
    if missing:
        problems.append(f"missing scenario files: {', '.join(missing)}")
    if problems:
        raise ScenarioError("\n".join(problems))
    return [found[scenario_id] for scenario_id in REQUIRED_IDS]
