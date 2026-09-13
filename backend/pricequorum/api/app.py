"""The PriceQuorum HTTP API (docs/contracts/api.md).

Designed for a single free web instance: migrations and the signing key are applied idempotently at
startup without calling any vendor. Slack Socket Mode, the approval sweeper, the drift monitor and the
sandbox worker run on daemon threads in this process, the MCP server is mounted at /mcp/, and
/api/health stays cheap.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sse_starlette.sse import EventSourceResponse

from mcp_server.server import build_mcp_app
from pricequorum import approvals, db, events, ledger, proof, resolver
from pricequorum.adapters_factory import AdapterSet, build_adapter_set
from pricequorum.config import Settings, get_settings
from pricequorum.monitor import DriftMonitor, heal_and_report
from pricequorum.orchestrator import PREAPPROVED_MODE, Orchestrator
from pricequorum.policy import MATCH_THRESHOLD
from pricequorum.sandbox import (
    AirtableLockSetter,
    LockSetter,
    Sandbox,
    SandboxBusy,
    SandboxScenario,
    SandboxUnavailable,
)

log = logging.getLogger("pricequorum.api")

SWEEP_SECONDS = 15
CHANGE_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
Outcome = Literal["SUCCESS", "PARTIAL", "REFUSED", "NEEDS_HUMAN"]


class RunCreateRequest(BaseModel):
    request_text: str = Field(min_length=1, max_length=500)
    change_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{1,64}$")
    fault: str | None = Field(default=None, description="Named fault scenario. Requires X-Operator-Token.")
    approval_mode: Literal["slack", "sandbox_auto"] = Field(
        default="slack", description="sandbox_auto approves immediately. Requires X-Operator-Token."
    )


class RunCreatedResponse(BaseModel):
    run_id: str
    events_url: str


class ApprovalBody(BaseModel):
    decision: Literal["approve", "deny"]


class ApprovalResult(BaseModel):
    decision: str


class HealthResponse(BaseModel):
    ok: bool
    version: str
    commit_sha: str
    db: Literal["ok", "down"]
    stripe_mode: Literal["test", "unconfigured"]
    slack_socket: Literal["connected", "down"]
    apps: dict[str, str]


class EvalResultIn(BaseModel):
    scenario_id: str = Field(min_length=1, max_length=80)
    description: str | None = None
    expected_outcome: Outcome | None = Field(
        default=None, description="Null or empty for a detection scenario, such as chain_tamper, that starts no run."
    )
    observed_outcome: str | None = Field(
        default=None, description="One outcome, or outcomes joined with '+' when the scenario starts several runs."
    )
    passed: bool
    run_id: UUID | None = None
    detail: str | None = None
    duplicate_writes_prevented: int = Field(default=0, ge=0)
    forbidden_refused: int = Field(default=0, ge=0)
    forbidden_attempted: int = Field(default=0, ge=0)

    @field_validator("expected_outcome", mode="before")
    @classmethod
    def _blank_expected(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value


class EvalRunIn(BaseModel):
    run_at: datetime | None = None
    commit_sha: str | None = None
    results: list[EvalResultIn] = Field(min_length=1)


class EvalRunRecorded(BaseModel):
    batch_id: str
    results: int


class PlanSide(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    interval: str = Field(default="", max_length=20)


class MatchRequest(BaseModel):
    left: PlanSide
    right: PlanSide


class MatchResult(BaseModel):
    match: bool
    score: int
    decision: Literal["fuzzy", "human", "different_currency", "different_interval"]
    threshold: int
    detail: str


class SandboxRunRequest(BaseModel):
    scenario: SandboxScenario


class SandboxRunsCreated(BaseModel):
    run_ids: list[str]
    events_urls: list[str]
    sandbox_plan_key: str
    approval_mode: Literal["sandbox_auto"]


class SandboxStatus(BaseModel):
    available: bool
    queue_depth: int
    cooldown_seconds: int


class HealRequest(BaseModel):
    plan_key: str = Field(pattern=r"^[A-Za-z0-9_:-]{1,64}$")


def _error(status: int, error: str, detail: str, remedy: str | None = None, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, "detail": detail, "remedy": remedy, **extra})


def _rate_limited(detail: str, remedy: str, retry_after: int) -> JSONResponse:
    response = _error(429, "rate_limited", detail, remedy, retry_after=retry_after)
    response.headers["retry-after"] = str(retry_after)
    return response


class _RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client: str, per_minute: int) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[client]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= per_minute:
                return False, max(1, int(60 - (now - hits[0])))
            hits.append(now)
            return True, 0


def _sweeper(stop: threading.Event) -> None:
    while not stop.wait(SWEEP_SECONDS):
        try:
            expired = approvals.expire_due()
            if expired:
                log.info("expired approvals: %s", ", ".join(expired))
        except Exception:  # noqa: BLE001 - the sweeper must keep running
            log.exception("approval sweeper failed")


def _start_approval(adapters: AdapterSet) -> None:
    if adapters.approval is None:
        return
    try:
        adapters.approval.start(approvals.decide)
    except Exception:  # noqa: BLE001 - Slack being down must not stop the API; health reports it
        log.exception("Slack approval connection failed to start")


def _monitor_message(envelope: dict[str, Any]) -> dict[str, str]:
    return {"id": str(envelope["seq"]), "event": envelope["type"], "data": json.dumps(envelope)}


def _summary(run_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        run = conn.execute("select * from runs where id = %s", (run_id,)).fetchone()
        if run is None:
            return None
        resolution = conn.execute(
            "select * from entity_resolution where run_id = %s order by id desc limit 1", (run_id,)
        ).fetchone()
        approval = conn.execute("select * from approvals where run_id = %s", (run_id,)).fetchone()
        rows = conn.execute(
            """select l.*, c.prev_hash, c.entry_hash from action_ledger l
               left join ledger_chain c on c.id = l.chain_id where l.run_id = %s order by l.step_no, l.id""",
            (run_id,),
        ).fetchall()
    run_events = events.list_events(run_id)
    intent = next((e["payload"] for e in run_events if e["type"] == "intent.parsed"), None)
    outcome = next((e["payload"] for e in reversed(run_events) if e["type"] == "run.outcome"), None)
    readbacks: dict[str, Any] = {}
    invariants: dict[str, Any] = {}
    for event in run_events:
        if event["type"] == "readback.result":
            readbacks[event["payload"]["app"]] = event["payload"]
        elif event["type"] == "invariant.result":
            invariants[event["payload"]["name"]] = event["payload"]
    new_price = next(
        (r["external_object_id"] for r in rows if r["action"] == "create_price" and r["state"] == "completed"), None
    )
    return {
        "run_id": run_id,
        "request_text": run["request_text"],
        "status": run["status"],
        "outcome": run["outcome"],
        "remedy": run["remedy"],
        "created_at": events.iso(run["created_at"]),
        "plan_key": run["plan_key"],
        "new_amount": intent["new_amount"] if intent else None,
        "resolution": (
            {
                "plan_key": resolution["plan_key"],
                "stripe_product_id": resolution["stripe_product_id"],
                "stripe_price_id_old": resolution["stripe_price_id"],
                "stripe_price_id_new": new_price,
                "notion_page_id": resolution["notion_page_id"],
                "airtable_record_id": resolution["airtable_record_id"],
                "confidence": resolution["confidence"],
                "decided_by": resolution["decided_by"],
            }
            if resolution
            else None
        ),
        "approval": (
            {
                "decision": approval["status"],
                "mode": approval["mode"],
                "approver_display": approval["approver_display"],
                "decided_at": events.iso(approval["decided_at"]) if approval["decided_at"] else None,
                "expires_at": events.iso(approval["expires_at"]),
                "slack_channel": approval["slack_channel"],
                "slack_ts": approval["slack_ts"],
                "args_hash": approval["args_hash"],
            }
            if approval
            else None
        ),
        "readback": list(readbacks.values()),
        "invariants": list(invariants.values()),
        "invariants_expected": list(run["invariants_expected"] or []),
        "ledger": [
            {
                "id": r["id"],
                "run_id": run_id,
                "step_no": r["step_no"],
                "app": r["app"],
                "action": r["action"],
                "idempotency_key": r["idempotency_key"],
                "args_hash": r["args_hash"],
                "state": r["state"],
                "external_object_id": r["external_object_id"],
                "outcome": r["outcome"],
                "remedy": r["remedy"],
                "prev_hash": r["prev_hash"],
                "entry_hash": r["entry_hash"],
                "created_at": events.iso(r["created_at"]),
                "completed_at": events.iso(r["completed_at"]) if r["completed_at"] else None,
            }
            for r in rows
        ],
        "chain_head": outcome["chain_head"] if outcome else None,
        "signature": outcome["signature"] if outcome else None,
        "public_key": outcome["public_key"] if outcome else ledger.public_key_hex(),
    }


def create_app(settings: Settings | None = None, adapters: AdapterSet | None = None) -> FastAPI:
    config = settings or get_settings()
    limiter = _RateLimiter()
    mcp_app = build_mcp_app(config.public_base_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        opened = db.init(config.database_url)
        db.migrate()
        ledger.load_signing_key(config.pq_signing_key)
        built = adapters if adapters is not None else build_adapter_set(config)
        orchestrator = Orchestrator(config, built, adapters_for_fault=lambda fault: build_adapter_set(config, fault))
        monitor = DriftMonitor(built, config.pq_monitor_interval_seconds)
        locker: LockSetter | None = (
            built.airtable if isinstance(built.airtable, LockSetter) else AirtableLockSetter.from_settings(config)
        )
        sandbox = Sandbox(config, orchestrator, monitor, locker)
        app.state.adapters = built
        app.state.orchestrator = orchestrator
        app.state.monitor = monitor
        app.state.sandbox = sandbox
        stop = threading.Event()
        threading.Thread(target=_start_approval, args=(built,), name="slack-socket", daemon=True).start()
        threading.Thread(target=_sweeper, args=(stop,), name="approval-sweeper", daemon=True).start()
        threading.Thread(target=monitor.run, args=(stop,), name="drift-monitor", daemon=True).start()
        threading.Thread(target=sandbox.run_worker, args=(stop,), name="sandbox-worker", daemon=True).start()
        orchestrator.recover_interrupted()
        try:
            # A mounted app's lifespan does not run by itself, so the MCP session manager starts here.
            async with mcp_app.state.mcp_server.session_manager.run():
                yield
        finally:
            stop.set()
            monitor.trigger()
            if opened:
                db.close()

    app = FastAPI(
        title="PriceQuorum API",
        version=config.pq_version,
        description="Changes one SaaS plan price exactly once across Stripe, Notion and Airtable, approved in Slack.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["retry-after"],
    )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        return _error(
            422,
            "validation_error",
            f"{where}: {first.get('msg', 'invalid request')}",
            "Fix the named field and send the request again.",
        )

    def operator_ok(token: str | None) -> bool:
        expected = config.pq_operator_token
        return bool(expected and token and hmac.compare_digest(token, expected))

    def client_address(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    @app.get("/api/health", response_model=HealthResponse)
    def health(request: Request) -> dict[str, Any]:
        built: AdapterSet = request.app.state.adapters
        db_ok = db.healthy()
        apps = {
            name: ("configured" if getattr(built, name) is not None else "not configured")
            for name in ("stripe", "notion", "airtable", "approval")
        }
        slack = "connected" if built.approval is not None and built.approval.connected() else "down"
        ok = (
            db_ok
            and all(value == "configured" for value in apps.values())
            and slack == "connected"
            and config.stripe_mode == "test"
        )
        return {
            "ok": ok,
            "version": config.pq_version,
            "commit_sha": config.pq_commit_sha,
            "db": "ok" if db_ok else "down",
            "stripe_mode": config.stripe_mode,
            "slack_socket": slack,
            "apps": apps,
        }

    @app.post("/api/runs", status_code=202, response_model=RunCreatedResponse)
    def create_run(
        body: RunCreateRequest, request: Request, x_operator_token: str | None = Header(default=None)
    ) -> Any:
        if (body.fault or body.approval_mode != "slack") and not operator_ok(x_operator_token):
            return _error(
                403,
                "operator_required",
                "Fault injection and sandbox approval are for the evaluation suite only.",
                "Send a valid X-Operator-Token header, or omit fault and approval_mode.",
            )
        if body.fault:
            from pricequorum.adapters.faults import injector_for

            try:
                injector_for(body.fault)
            except ValueError as exc:
                return _error(422, "unknown_fault", str(exc), "Use a fault name from pricequorum/adapters/faults.py.")
        allowed, retry_after = limiter.allow(client_address(request), config.pq_runs_per_minute)
        if not allowed:
            return _rate_limited(
                "Too many runs from this address.", f"Try again in {retry_after} seconds.", retry_after
            )
        orchestrator: Orchestrator = request.app.state.orchestrator
        run_id = orchestrator.create_run(body.request_text, body.change_key, body.approval_mode, body.fault)
        orchestrator.start(run_id)
        return {"run_id": run_id, "events_url": f"/api/runs/{run_id}/events"}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: UUID) -> Any:
        summary = _summary(str(run_id))
        if summary is None:
            return _error(404, "run_not_found", f"No run {run_id}.", "Check the run id from POST /api/runs.")
        return summary

    @app.get("/api/runs/{run_id}/events.json", response_model=list[events.EventEnvelope])  # type: ignore[valid-type]
    def events_json(run_id: UUID) -> Any:
        if _summary_exists(str(run_id)) is False:
            return _error(404, "run_not_found", f"No run {run_id}.", "Check the run id from POST /api/runs.")
        return events.list_events(str(run_id))

    def _summary_exists(run_id: str) -> bool:
        with db.connect() as conn:
            return conn.execute("select 1 from runs where id = %s", (run_id,)).fetchone() is not None

    @app.get("/api/runs/{run_id}/events")
    async def stream(run_id: UUID, request: Request, last_event_id: str | None = Header(default=None)) -> Any:
        if not await run_in_threadpool(_summary_exists, str(run_id)):
            return _error(404, "run_not_found", f"No run {run_id}.", "Check the run id from POST /api/runs.")
        start = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

        async def generate() -> AsyncIterator[dict[str, str]]:
            after = start
            while True:
                if await request.is_disconnected():
                    return
                batch = await run_in_threadpool(events.list_events, str(run_id), after)
                for envelope in batch:
                    after = envelope["seq"]
                    yield {"id": str(envelope["seq"]), "event": envelope["type"], "data": json.dumps(envelope)}
                    if envelope["type"] == "run.outcome":
                        return
                await asyncio.sleep(0.5)

        return EventSourceResponse(generate(), ping=15)

    @app.post("/api/runs/{run_id}/approval", response_model=ApprovalResult)
    def operator_approval(run_id: UUID, body: ApprovalBody, x_operator_token: str | None = Header(default=None)) -> Any:
        if not config.pq_operator_token:
            return _error(
                403, "operator_disabled", "The operator approval fallback is not enabled.", "Approve in Slack."
            )
        if not operator_ok(x_operator_token):
            return _error(
                401, "bad_operator_token", "X-Operator-Token is missing or wrong.", "Send the operator token."
            )
        result = approvals.decide(str(run_id), body.decision, "operator")
        if result == "NOT_FOUND":
            return _error(
                404, "approval_not_found", f"Run {run_id} has no approval request.", "Wait for approval.requested."
            )
        if result == "ALREADY_DECIDED":
            return _error(
                409, "already_decided", "This approval was already decided.", "Read the run to see the decision."
            )
        return {"decision": result}

    @app.get("/api/ledger/export")
    def ledger_export(run_id: UUID | None = None) -> Any:
        # The whole chain is always returned so a browser can verify it from the genesis value.
        return ledger.export()

    @app.post("/api/ledger/verify")
    def ledger_verify() -> Any:
        return ledger.verify()

    @app.get("/api/public-key")
    def public_key() -> Any:
        return {"public_key": ledger.public_key_hex(), "algorithm": "ed25519"}

    @app.get("/api/proof")
    def get_proof() -> Any:
        return proof.compute_proof(config.pq_commit_sha)

    @app.get("/api/evals/latest")
    def get_evals_latest() -> Any:
        return proof.evals_latest(config.pq_commit_sha)

    @app.post("/api/evals/results", status_code=201, response_model=EvalRunRecorded)
    def post_eval_results(body: EvalRunIn, x_operator_token: str | None = Header(default=None)) -> Any:
        if not operator_ok(x_operator_token):
            return _error(
                403,
                "operator_required",
                "Recording evaluation results needs the operator token.",
                "Send X-Operator-Token.",
            )
        rows = [
            {**result.model_dump(), "run_id": str(result.run_id) if result.run_id else None} for result in body.results
        ]
        batch_id = proof.record_eval_run(body.run_at, body.commit_sha, rows)
        return {"batch_id": batch_id, "results": len(rows)}

    @app.post("/api/resolver/match", response_model=MatchResult)
    def resolver_match(body: MatchRequest) -> Any:
        left, right = body.left, body.right
        result = resolver.match_pair(
            left.label, left.currency, left.interval, right.label, right.currency, right.interval
        )
        return {
            "match": result.match,
            "score": result.score,
            "decision": result.decision,
            "threshold": MATCH_THRESHOLD,
            "detail": result.detail,
        }

    @app.post("/api/sandbox/runs", status_code=202, response_model=SandboxRunsCreated)
    def sandbox_runs(body: SandboxRunRequest, request: Request) -> Any:
        sandbox: Sandbox = request.app.state.sandbox
        try:
            job = sandbox.submit(body.scenario, client_address(request))
        except SandboxUnavailable as exc:
            return _error(503, "sandbox_unavailable", exc.detail, exc.remedy)
        except SandboxBusy as exc:
            return _rate_limited(exc.detail, exc.remedy, exc.retry_after)
        return {
            "run_ids": job.run_ids,
            "events_urls": [f"/api/runs/{run_id}/events" for run_id in job.run_ids],
            "sandbox_plan_key": sandbox.plan_key,
            "approval_mode": "sandbox_auto",
        }

    @app.get("/api/sandbox/status", response_model=SandboxStatus)
    def sandbox_status(request: Request) -> Any:
        sandbox: Sandbox = request.app.state.sandbox
        return sandbox.status()

    @app.get("/api/monitor/events")
    async def monitor_events(request: Request, last_event_id: str | None = Header(default=None)) -> Any:
        monitor: DriftMonitor = request.app.state.monitor

        async def generate() -> AsyncIterator[dict[str, str]]:
            monitor.add_listener()
            try:
                if last_event_id and last_event_id.isdigit():
                    after = int(last_event_id)
                else:
                    after = monitor.last_seq
                    for envelope in monitor.snapshot():
                        yield _monitor_message(envelope)
                while True:
                    if await request.is_disconnected():
                        return
                    for envelope in monitor.events_after(after):
                        after = envelope["seq"]
                        yield _monitor_message(envelope)
                    await asyncio.sleep(0.5)
            finally:
                monitor.remove_listener()

        return EventSourceResponse(generate(), ping=15)

    @app.post("/api/monitor/heal", status_code=202, response_model=RunCreatedResponse)
    def monitor_heal(body: HealRequest, request: Request, x_operator_token: str | None = Header(default=None)) -> Any:
        if not operator_ok(x_operator_token):
            return _error(
                403,
                "operator_required",
                "Starting a heal run needs the operator token; the token is recorded as the approval.",
                "Send a valid X-Operator-Token header.",
            )
        orchestrator: Orchestrator = request.app.state.orchestrator
        missing = orchestrator.adapters.missing_apps()
        if missing:
            names = ", ".join(name.capitalize() for name in missing)
            return _error(
                503, "apps_not_configured", f"{names} not configured.", f"Set the credentials for {names} and restart."
            )
        run_id = orchestrator.create_run(
            f"Heal drift on {body.plan_key}: write the Stripe price to Notion and Airtable.",
            approval_mode=PREAPPROVED_MODE,
            plan_scope=body.plan_key,
        )
        threading.Thread(
            target=heal_and_report,
            args=(orchestrator, request.app.state.monitor, run_id, body.plan_key),
            name=f"heal-{run_id[:8]}",
            daemon=True,
        ).start()
        return {"run_id": run_id, "events_url": f"/api/runs/{run_id}/events"}

    app.mount("/mcp", mcp_app)
    return app


app = create_app()
