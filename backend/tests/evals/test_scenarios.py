import json
import shutil
from pathlib import Path

import pytest

from evals.scenario import (
    PLAN_CURRENCY,
    REQUIRED_IDS,
    SCENARIO_DIR,
    ScenarioError,
    load_scenarios,
    problems_in,
)


def test_all_twenty_scenarios_load_in_matrix_order():
    scenarios = load_scenarios()
    assert [scenario.id for scenario in scenarios] == list(REQUIRED_IDS)
    assert len(scenarios) == 20


def test_every_scenario_is_runnable_or_states_why_not():
    for scenario in load_scenarios():
        if scenario.runnable:
            assert scenario.not_runnable_reason is None, scenario.id
        else:
            assert scenario.not_runnable_reason and len(scenario.not_runnable_reason) > 40, scenario.id


def test_runnable_scenarios_that_start_a_run_assert_an_outcome_and_an_end_state():
    for scenario in load_scenarios():
        if scenario.runnable and scenario.approval != "none":
            assert scenario.request_text, scenario.id
            assert scenario.expected_outcome is not None, scenario.id
            assert scenario.expected_end_state, scenario.id
            for plans in scenario.expected_end_state.values():
                assert set(plans) <= set(PLAN_CURRENCY)


def test_forbidden_scenarios_expect_a_refusal():
    for scenario in load_scenarios():
        if scenario.forbidden:
            assert scenario.expected_outcome == "REFUSED", scenario.id


def test_missing_and_malformed_files_are_reported_not_skipped(tmp_path: Path):
    for path in SCENARIO_DIR.glob("*.json"):
        shutil.copy(path, tmp_path / path.name)
    (tmp_path / "happy_path.json").unlink()
    broken = json.loads((tmp_path / "forbidden_edit.json").read_text())
    broken["runnable"] = False
    broken["not_runnable_reason"] = None
    (tmp_path / "forbidden_edit.json").write_text(json.dumps(broken))
    with pytest.raises(ScenarioError) as raised:
        load_scenarios(tmp_path)
    message = str(raised.value)
    assert "missing scenario files: happy_path" in message
    assert "forbidden_edit.json: a scenario that is not runnable must state not_runnable_reason" in message


def test_schema_rejects_float_money_and_unknown_faults():
    data = json.loads((SCENARIO_DIR / "happy_path.json").read_text())
    data["expected_end_state"] = {"stripe": {"pro": 25.0}}
    data["fault"] = "gremlins"
    problems = problems_in(data, "happy_path.json")
    assert any("integer minor units" in problem for problem in problems)
    assert any("fault must be null" in problem for problem in problems)
