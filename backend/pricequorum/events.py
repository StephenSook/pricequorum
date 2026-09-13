"""Run events: the typed payloads of docs/contracts/api.md. Each event is written to run_events
before anything publishes it, so a reconnecting client can replay the exact same sequence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Union

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, create_model

from pricequorum import db

OutcomeLiteral = Literal["SUCCESS", "PARTIAL", "REFUSED", "NEEDS_HUMAN"]
ApprovalMode = Literal["slack", "operator", "sandbox_auto"]


class MoneyModel(BaseModel):
    minor_units: int
    currency: str


class RunCreated(BaseModel):
    request_text: str


class RunStatusPayload(BaseModel):
    status: Literal["running", "awaiting_human", "done", "refused", "failed"]


class IntentParsed(BaseModel):
    plan_hint: str
    new_amount: MoneyModel
    interval: Literal["month", "year"]


class Candidate(BaseModel):
    app: str
    label: str
    score: int


class ResolveCompleted(BaseModel):
    plan_key: str | None
    stripe_product_id: str | None
    stripe_price_id: str | None
    notion_page_id: str | None
    airtable_record_id: str | None
    confidence: int
    decided_by: Literal["exact_id", "fuzzy", "human"]
    candidates: list[Candidate]


class PolicyDecided(BaseModel):
    decision: Literal["ALLOW", "REFUSED", "NEEDS_HUMAN"]
    rule: str
    detail: str
    remedy: str | None


class ApprovalRequested(BaseModel):
    summary: str
    args_hash: str
    slack_channel: str | None
    slack_ts: str | None
    expires_at: str
    mode: ApprovalMode


class ApprovalDecided(BaseModel):
    decision: Literal["PENDING", "APPROVED", "DENIED", "EXPIRED"]
    approver_display: str | None
    decided_at: str | None
    mode: ApprovalMode


class LedgerPending(BaseModel):
    ledger_id: int
    step_no: int
    app: str
    action: str
    idempotency_key: str
    args_hash: str


class AdapterFaultPayload(BaseModel):
    ledger_id: int
    call_site: str
    kind: Literal["timeout", "rate_limit", "conflict_409", "server_5xx"]
    injected: bool


class ReadbackRecovery(BaseModel):
    ledger_id: int
    call_site: str
    found_landed: bool
    external_object_id: str | None


class LedgerCompleted(BaseModel):
    ledger_id: int
    step_no: int
    external_object_id: str
    prev_hash: str
    entry_hash: str


class SubscriptionMigrated(BaseModel):
    subscription_id: str
    from_price: str
    to_price: str
    proration_behavior: str


class RenewalInvoice(BaseModel):
    invoice_id: str
    amount: MoneyModel
    test_clock_id: str | None


class ReadbackResultPayload(BaseModel):
    app: str
    value: MoneyModel | None
    raw_value: str | None
    fresh: bool
    read_at: str
    source_id: str


class InvariantResultPayload(BaseModel):
    name: str
    ok: bool
    detail: str
    outcome: OutcomeLiteral


class RunOutcomePayload(BaseModel):
    outcome: OutcomeLiteral
    remedy: str | None
    chain_head: str
    signature: str
    public_key: str
    invariants_expected: list[str]


PAYLOADS: dict[str, type[BaseModel]] = {
    "run.created": RunCreated,
    "run.status": RunStatusPayload,
    "intent.parsed": IntentParsed,
    "resolve.completed": ResolveCompleted,
    "policy.decided": PolicyDecided,
    "approval.requested": ApprovalRequested,
    "approval.decided": ApprovalDecided,
    "ledger.pending": LedgerPending,
    "adapter.fault": AdapterFaultPayload,
    "readback.recovery": ReadbackRecovery,
    "ledger.completed": LedgerCompleted,
    "subscription.migrated": SubscriptionMigrated,
    "renewal.invoice": RenewalInvoice,
    "readback.result": ReadbackResultPayload,
    "invariant.result": InvariantResultPayload,
    "run.outcome": RunOutcomePayload,
}


def _envelope_model(type_name: str, payload: type[BaseModel]) -> type[BaseModel]:
    model_name = "Event" + "".join(part.capitalize() for part in type_name.replace(".", "_").split("_"))
    return create_model(  # type: ignore[call-overload,no-any-return]
        model_name,
        seq=(int, ...),
        run_id=(str, ...),
        type=(Literal[type_name], ...),  # type: ignore[valid-type]
        at=(str, ...),
        payload=(payload, ...),
    )


ENVELOPES: dict[str, type[BaseModel]] = {name: _envelope_model(name, model) for name, model in PAYLOADS.items()}

# One discriminated union on `type`, exported to shared/openapi.json.
EventEnvelope = Annotated[Union[tuple(ENVELOPES.values())], Field(discriminator="type")]  # type: ignore[valid-type]  # noqa: UP007


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def now_iso() -> str:
    return iso(datetime.now(UTC))


def emit(run_id: str, type_name: str, payload: BaseModel) -> dict[str, Any]:
    """Persists one event with the next sequence number for the run and returns its envelope."""
    expected = PAYLOADS.get(type_name)
    if expected is None or not isinstance(payload, expected):
        raise TypeError(f"{type_name} expects {expected.__name__ if expected else 'a known event type'}")
    data = payload.model_dump(mode="json")
    with db.connect() as conn, conn.transaction():
        seq_row = conn.execute(
            "update runs set last_seq = last_seq + 1 where id = %s returning last_seq", (run_id,)
        ).fetchone()
        if seq_row is None:
            raise LookupError(f"run {run_id} not found")
        at_row = conn.execute(
            "insert into run_events (run_id, seq, type, payload) values (%s, %s, %s, %s) returning at",
            (run_id, seq_row["last_seq"], type_name, Jsonb(data)),
        ).fetchone()
    assert at_row is not None
    return {"seq": seq_row["last_seq"], "run_id": run_id, "type": type_name, "at": iso(at_row["at"]), "payload": data}


def list_events(run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            "select seq, run_id, type, payload, at from run_events where run_id = %s and seq > %s order by seq",
            (run_id, after_seq),
        ).fetchall()
    return [
        {
            "seq": row["seq"],
            "run_id": str(row["run_id"]),
            "type": row["type"],
            "at": iso(row["at"]),
            "payload": row["payload"],
        }
        for row in rows
    ]
