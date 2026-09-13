"""Runs the PriceQuorum evaluation suite against the deployed backend and real test-mode vendors.

Usage, from backend/:
    uv run python -m evals.run_evals --base-url https://<backend> [--only happy_path,forbidden_edit]
        [--runs-per-scenario 1] [--ci] [--no-post] [--output report.json]
    uv run python -m evals.run_evals --validate-only

Environment: PQ_OPERATOR_TOKEN, STRIPE_SECRET_KEY, NOTION_TOKEN, NOTION_DATA_SOURCE_ID, AIRTABLE_PAT,
AIRTABLE_BASE_ID, AIRTABLE_TABLE, and optionally PQ_BASE_URL and PQ_COMMIT_SHA. Prints results only,
never a secret. A scenario that cannot run is reported as a failure with its reason.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.harness import TrialResult, build_report, evaluate, not_runnable  # noqa: E402
from evals.scenario import ScenarioError, load_scenarios  # noqa: E402


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PriceQuorum evaluation suite")
    parser.add_argument("--base-url", default=os.environ.get("PQ_BASE_URL"))
    parser.add_argument("--only", help="comma separated scenario ids")
    parser.add_argument("--runs-per-scenario", type=int, default=1)
    parser.add_argument("--ci", action="store_true", help="exit non-zero on any failure or if results are not stored")
    parser.add_argument("--no-post", action="store_true", help="do not POST the report to /api/evals/results")
    parser.add_argument("--output", help="also write the report JSON to this path")
    parser.add_argument("--validate-only", action="store_true", help="check the scenario files and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        scenarios = load_scenarios()
    except ScenarioError as error:
        print(f"scenario files are invalid:\n{error}")
        return 2
    if args.only:
        wanted = [item.strip() for item in args.only.split(",") if item.strip()]
        unknown = sorted(set(wanted) - {scenario.id for scenario in scenarios})
        if unknown:
            print(f"unknown scenario ids: {', '.join(unknown)}")
            return 2
        scenarios = [scenario for scenario in scenarios if scenario.id in wanted]
    if args.runs_per_scenario < 1:
        print("--runs-per-scenario must be at least 1")
        return 2

    runnable = [scenario for scenario in scenarios if scenario.runnable]
    if args.validate_only:
        print(
            f"{len(scenarios)} scenario files valid: {len(runnable)} runnable, {len(scenarios) - len(runnable)} not runnable"
        )
        for scenario in scenarios:
            if not scenario.runnable:
                print(f"  not runnable {scenario.id}: {scenario.not_runnable_reason}")
        return 0

    if not args.base_url:
        print("set --base-url or PQ_BASE_URL to the deployed backend")
        return 2
    token = os.environ.get("PQ_OPERATOR_TOKEN", "").strip()
    if not token:
        print(
            "set PQ_OPERATOR_TOKEN: the harness starts sandbox runs and denies approvals through the operator endpoint"
        )
        return 2

    from evals.live import BackendClient, HarnessError, VendorWorld, run_trial

    try:
        world = VendorWorld()
    except HarnessError as error:
        print(f"cannot read the vendors: {error}")
        return 2
    backend = BackendClient(args.base_url, token)

    trials: list[TrialResult] = []
    for scenario in scenarios:
        for run_index in range(args.runs_per_scenario):
            if not scenario.runnable:
                trial = not_runnable(scenario, run_index)
            else:
                trial = evaluate(scenario, run_trial(scenario, backend, world), run_index)
            trials.append(trial)
            label = "PASS" if trial.passed else "FAIL"
            print(f"{label} {scenario.id} run {run_index + 1}: {trial.observed_outcome} ({trial.detail})", flush=True)

    report = build_report(
        scenarios,
        trials,
        args.runs_per_scenario,
        os.environ.get("PQ_COMMIT_SHA") or None,
        datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    summary = report["summary"]
    low, high = summary["wilson_95"]
    print(
        f"{summary['passed']}/{summary['total']} scenarios passed, 95% Wilson interval {low:.3f} to {high:.3f}, "
        f"{summary['runs_per_scenario']} run(s) each"
    )
    print("outcomes: " + ", ".join(f"{name} {count}" for name, count in report["outcomes"].items()))
    print(f"duplicate writes prevented: {report['duplicate_writes_prevented']}")
    refusals = report["forbidden_actions_refused"]
    print(f"forbidden actions refused: {refusals['refused']}/{refusals['attempted']}")
    for failure in report["named_failures"]:
        print(f"named failure {failure['scenario_id']}: {failure['explanation']}")

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    stored = True
    if not args.no_post:
        status, detail = backend.post_results(report)
        stored = 200 <= status < 300
        print(f"POST /api/evals/results: {status} {detail}".rstrip())
    if args.ci and (summary["passed"] != summary["total"] or not stored):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
