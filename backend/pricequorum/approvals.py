"""The approval gate's storage. A decision is a single-winner transition: the first click (Slack or
operator) moves PENDING to APPROVED or DENIED, and every later click sees ALREADY_DECIDED."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pricequorum import db


def create(run_id: str, action: str, summary: str, args_hash: str, mode: str, ttl_seconds: int) -> dict[str, Any]:
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    with db.connect() as conn:
        row = conn.execute(
            """insert into approvals (run_id, action, summary, args_hash, mode, expires_at)
               values (%s, %s, %s, %s, %s, %s) returning *""",
            (run_id, action, summary, args_hash, mode, expires_at),
        ).fetchone()
    assert row is not None
    return dict(row)


def set_posted(run_id: str, channel: str, ts: str) -> None:
    with db.connect() as conn:
        conn.execute("update approvals set slack_channel = %s, slack_ts = %s where run_id = %s", (channel, ts, run_id))


def get(run_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute("select * from approvals where run_id = %s", (run_id,)).fetchone()
    return dict(row) if row else None


def decide(run_id: str, decision: str, approver_display: str, args_hash: str | None = None) -> str:
    """Applies one decision. Returns APPROVED, DENIED, EXPIRED, ALREADY_DECIDED, NOT_FOUND or ARGS_MISMATCH.

    When args_hash is given (the Slack button carries it), the decision binds to that exact action, so
    a stale button can never approve a different change."""
    if decision not in ("approve", "deny"):
        raise ValueError("decision must be approve or deny")
    status = "APPROVED" if decision == "approve" else "DENIED"
    with db.connect() as conn, conn.transaction():
        current = conn.execute(
            "select status, args_hash, expires_at from approvals where run_id = %s for update", (run_id,)
        ).fetchone()
        if current is None:
            return "NOT_FOUND"
        if args_hash is not None and args_hash != current["args_hash"]:
            return "ARGS_MISMATCH"
        if current["status"] != "PENDING":
            return "ALREADY_DECIDED"
        if current["expires_at"] <= datetime.now(UTC):
            conn.execute("update approvals set status = 'EXPIRED', decided_at = now() where run_id = %s", (run_id,))
            return "EXPIRED"
        updated = conn.execute(
            """update approvals set status = %s, approver_display = %s, decided_at = now()
               where run_id = %s and status = 'PENDING' returning status""",
            (status, approver_display, run_id),
        ).fetchone()
    return status if updated else "ALREADY_DECIDED"


def expire_due() -> list[str]:
    """The sweeper: marks every pending approval past its deadline as EXPIRED."""
    with db.connect() as conn:
        rows = conn.execute(
            """update approvals set status = 'EXPIRED', decided_at = now()
               where status = 'PENDING' and expires_at <= now() returning run_id"""
        ).fetchall()
    return [str(row["run_id"]) for row in rows]
