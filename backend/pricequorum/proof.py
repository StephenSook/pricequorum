"""GET /api/proof and GET /api/evals/latest, recomputed from the database on every request, and the
operator endpoint that records one evaluation run. When no evaluation has run, the totals are zero and
the lists are empty; nothing is invented."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from math import sqrt
from typing import Any

from pricequorum import db, ledger
from pricequorum.events import iso

OUTCOMES = ("SUCCESS", "PARTIAL", "REFUSED", "NEEDS_HUMAN")


def wilson_interval(passed: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total == 0:
        return None
    p = passed / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


def count_outcomes(observed: list[str | None]) -> dict[str, int]:
    """Counts run outcomes. A scenario that starts several runs records them joined with '+', for example
    REFUSED+SUCCESS; each part counts once. A part that is not a run outcome (NONE for a run that never
    finished) and a null observation (a detection scenario that starts no run) count toward nothing."""
    counts = dict.fromkeys(OUTCOMES, 0)
    for value in observed:
        for part in (value or "").split("+"):
            if part.strip() in counts:
                counts[part.strip()] += 1
    return counts


def record_eval_run(run_at: datetime | None, commit_sha: str | None, results: list[dict[str, Any]]) -> str:
    """Stores one evaluation run as a batch. Scenario descriptions and expected outcomes are upserted."""
    batch_id = str(uuid.uuid4())
    ran_at = run_at or datetime.now(UTC)
    with db.connect() as conn, conn.transaction():
        for result in results:
            conn.execute(
                """insert into eval_scenarios (id, description, request, expected_outcome)
                   values (%s, %s, '', %s)
                   on conflict (id) do update set description = excluded.description,
                     expected_outcome = excluded.expected_outcome""",
                (
                    result["scenario_id"],
                    result.get("description") or result["scenario_id"],
                    result.get("expected_outcome"),
                ),
            )
            conn.execute(
                """insert into eval_results (batch_id, scenario_id, run_id, passed, observed_outcome, detail, commit_sha,
                     ran_at, duplicate_writes_prevented, forbidden_refused, forbidden_attempted)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    batch_id,
                    result["scenario_id"],
                    result.get("run_id"),
                    result["passed"],
                    result.get("observed_outcome"),
                    result.get("detail"),
                    commit_sha,
                    ran_at,
                    int(result.get("duplicate_writes_prevented") or 0),
                    int(result.get("forbidden_refused") or 0),
                    int(result.get("forbidden_attempted") or 0),
                ),
            )
    return batch_id


def _latest_batch_rows(conn: Any) -> list[dict[str, Any]]:
    latest = conn.execute("select batch_id from eval_results order by ran_at desc, id desc limit 1").fetchone()
    if latest is None:
        return []
    return conn.execute(
        """select r.*, s.description, s.expected_outcome
           from eval_results r join eval_scenarios s on s.id = r.scenario_id
           where r.batch_id = %s order by r.id""",
        (latest["batch_id"],),
    ).fetchall()


def _explanation(row: dict[str, Any]) -> str:
    if row["detail"]:
        return str(row["detail"])
    expected = row["expected_outcome"] or "the detection to hold"
    return f"expected {expected}, observed {row['observed_outcome']}"


def compute_proof(commit_sha: str) -> dict[str, Any]:
    with db.connect() as conn:
        rows = _latest_batch_rows(conn)
        live = conn.execute(
            """select count(*) as total, count(*) filter (where outcome = 'SUCCESS') as success
               from runs where scenario is null and approval_mode <> 'sandbox_auto' and outcome is not null"""
        ).fetchone()

    scenario_ids = list(dict.fromkeys(row["scenario_id"] for row in rows))
    passed_ids = [sid for sid in scenario_ids if all(r["passed"] for r in rows if r["scenario_id"] == sid)]
    runs_per_scenario = max((sum(1 for r in rows if r["scenario_id"] == sid) for sid in scenario_ids), default=0)
    failures: dict[str, str] = {}
    for row in rows:
        if not row["passed"] and row["scenario_id"] not in failures:
            failures[row["scenario_id"]] = _explanation(row)
    verification = ledger.verify()
    return {
        "generated_at": iso(datetime.now(UTC)),
        "commit_sha": commit_sha,
        "scenarios": {
            "passed": len(passed_ids),
            "total": len(scenario_ids),
            "wilson_95": wilson_interval(len(passed_ids), len(scenario_ids)),
            "runs_per_scenario": runs_per_scenario or None,
        },
        "outcomes": count_outcomes([r["observed_outcome"] for r in rows]),
        "duplicate_writes_prevented": sum(int(r["duplicate_writes_prevented"]) for r in rows),
        "forbidden_actions_refused": {
            "refused": sum(int(r["forbidden_refused"]) for r in rows),
            "attempted": sum(int(r["forbidden_attempted"]) for r in rows),
        },
        "named_failures": [{"scenario_id": sid, "explanation": text} for sid, text in failures.items()],
        "ledger": {
            "entries": verification["entries"],
            "chain_intact": verification["first_bad_id"] is None,
            "signature_valid": verification["signature_valid"],
        },
        "live_runs": {"total": int(live["total"]) if live else 0, "success": int(live["success"]) if live else 0},
        "last_eval_run_at": iso(max(r["ran_at"] for r in rows)) if rows else None,
    }


def evals_latest(commit_sha: str) -> dict[str, Any]:
    proof = compute_proof(commit_sha)
    with db.connect() as conn:
        rows = _latest_batch_rows(conn)
    return {
        "run_at": iso(max(r["ran_at"] for r in rows)) if rows else None,
        "commit_sha": rows[-1]["commit_sha"] if rows else None,
        "summary": proof["scenarios"],
        "results": [
            {
                "scenario_id": r["scenario_id"],
                "description": r["description"],
                "expected_outcome": r["expected_outcome"],
                "observed_outcome": r["observed_outcome"],
                "passed": r["passed"],
                "run_id": str(r["run_id"]) if r["run_id"] else None,
                "detail": r["detail"] or "",
            }
            for r in rows
        ],
    }
