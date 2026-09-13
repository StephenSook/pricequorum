"""The run loop. Deterministic code decides every step; the model only helps parse the request.

Order of events for one run (docs/contracts/api.md): run.created, intent.parsed, resolve.completed,
policy.decided, approval.requested, approval.decided, then for every write ledger.pending, an optional
adapter.fault and readback.recovery, ledger.completed; then readback.result for each app,
invariant.result for each check, and run.outcome. A refusal or a question for a person goes straight
to run.outcome after the event that decided it.

A heal run (execute_heal) follows the same order without intent.parsed. It reads the Stripe price and
writes only Notion and Airtable, so it can never change what a customer is charged.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

from pricequorum import approvals, db, events, ledger, policy, resolver, verifier
from pricequorum import intent as intent_mod
from pricequorum.adapters_factory import AdapterSet
from pricequorum.config import Settings
from pricequorum.events import (
    AdapterFaultPayload,
    ApprovalDecided,
    ApprovalRequested,
    Candidate,
    IntentParsed,
    InvariantResultPayload,
    LedgerCompleted,
    LedgerPending,
    MoneyModel,
    PolicyDecided,
    ReadbackRecovery,
    ReadbackResultPayload,
    ResolveCompleted,
    RunCreated,
    RunOutcomePayload,
    RunStatusPayload,
)
from pricequorum.money import format_money
from pricequorum.policy import Decision
from pricequorum.ports import (
    AdapterFault,
    AdapterRefusal,
    ApprovalPosted,
    ApprovalRequest,
    DerivedPort,
    Money,
    PlanRecord,
    WriteResult,
)

log = logging.getLogger("pricequorum.orchestrator")

UNPARSED_REMEDY = "State the plan and the new price, for example: raise Pro to $25/month."
STATUS_FOR_OUTCOME = {"SUCCESS": "done", "NEEDS_HUMAN": "done", "REFUSED": "refused", "PARTIAL": "failed"}
SANDBOX_APPROVER = "sandbox auto-approver"
HEAL_APPROVER = "operator token on POST /api/monitor/heal"
# A heal started with the operator token: the token is the approval, recorded as an operator decision.
PREAPPROVED_MODE = "operator_preapproved"

PlanLists = tuple[list[PlanRecord], list[PlanRecord], list[PlanRecord]]


class StepFailed(Exception):
    def __init__(self, outcome: str, detail: str, remedy: str) -> None:
        super().__init__(detail)
        self.outcome = outcome
        self.detail = detail
        self.remedy = remedy


def lookup_key_for(plan_key: str, currency: str, interval: str) -> str:
    """The stable Stripe lookup key moved to each new price (scripts/seed.py uses the same convention)."""
    return f"{plan_key}_{currency}_{interval}"


def _derived_write(port: DerivedPort, external_id: str, amount: Money) -> Callable[[str], WriteResult]:
    return lambda key: port.write_price(external_id, amount, key)


def _derived_landed(port: DerivedPort, external_id: str, amount: Money) -> Callable[[], str | None]:
    return lambda: external_id if port.read_back(external_id).value == amount else None


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        adapters: AdapterSet,
        adapters_for_fault: Callable[[str], AdapterSet] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.adapters = adapters
        self.adapters_for_fault = adapters_for_fault
        self.sleep = sleep

    # Run lifecycle -----------------------------------------------------------------

    def create_run(
        self,
        request_text: str,
        change_key: str | None = None,
        approval_mode: str = "slack",
        fault: str | None = None,
        plan_scope: str | None = None,
    ) -> str:
        with db.connect() as conn:
            row = conn.execute(
                """insert into runs (request_text, change_key, approval_mode, scenario, plan_scope)
                   values (%s, %s, %s, %s, %s) returning id""",
                (request_text, change_key, approval_mode, fault, plan_scope),
            ).fetchone()
        assert row is not None
        return str(row["id"])

    def start(self, run_id: str) -> threading.Thread:
        thread = threading.Thread(target=self.execute, args=(run_id,), name=f"run-{run_id[:8]}", daemon=True)
        thread.start()
        return thread

    def execute(self, run_id: str) -> None:
        try:
            self._execute(run_id)
        except Exception as exc:  # noqa: BLE001 - an unexpected error must still end the run honestly
            log.exception("run %s failed unexpectedly", run_id)
            self._finish(
                run_id,
                "PARTIAL",
                f"The run stopped on an unexpected {type(exc).__name__}. Read the ledger steps, then re-run the request "
                "with the same change key; completed steps are not repeated.",
                [],
            )

    def execute_heal(self, run_id: str, plan_key: str) -> list[str]:
        """Writes the Stripe price into Notion and Airtable for one plan; Stripe itself is never written. Returns
        the apps that were written, and only when the run then verified SUCCESS on fresh reads."""
        try:
            return self._execute_heal(run_id, plan_key)
        except Exception as exc:  # noqa: BLE001 - an unexpected error must still end the run honestly
            log.exception("heal run %s failed unexpectedly", run_id)
            self._finish(
                run_id,
                "PARTIAL",
                f"The heal stopped on an unexpected {type(exc).__name__}. Read the ledger steps, then start the heal again.",
                [],
            )
            return []

    def recover_interrupted(self) -> int:
        """Ends runs a previous process left unfinished. Pending ledger rows keep their idempotency keys, so
        re-running the same request reuses them and a write that already landed is never sent twice."""
        with db.connect() as conn:
            rows = conn.execute("select id, status from runs where outcome is null").fetchall()
        for row in rows:
            run_id = str(row["id"])
            with db.connect() as conn:
                conn.execute(
                    """update action_ledger set state = 'failed', outcome = 'PARTIAL',
                         remedy = 'The backend restarted before this step confirmed.'
                       where run_id = %s and state = 'pending'""",
                    (run_id,),
                )
                wrote = conn.execute("select count(*) as n from action_ledger where run_id = %s", (run_id,)).fetchone()
                conn.execute(
                    "update approvals set status = 'EXPIRED', decided_at = now() where run_id = %s and status = 'PENDING'",
                    (run_id,),
                )
            if wrote and wrote["n"]:
                self._finish(
                    run_id,
                    "PARTIAL",
                    "The backend restarted during this run. Re-run the request with the same change key; completed "
                    "steps are not repeated because every write reuses its idempotency key.",
                    [],
                )
            else:
                self._finish(
                    run_id,
                    "NEEDS_HUMAN",
                    "The backend restarted before this run wrote anything. Submit the request again.",
                    [],
                )
        return len(rows)

    # Public hooks for the sandbox, which records runs that are not price changes -------

    def emit(self, run_id: str, type_name: str, payload: Any) -> None:
        self._emit(run_id, type_name, payload)

    def finish(self, run_id: str, outcome: str, remedy: str | None, invariants_expected: list[str]) -> None:
        self._finish(run_id, outcome, remedy, invariants_expected)

    def end_before_start(self, run_id: str, decision: Decision) -> None:
        """Records run.created and the deciding policy event for a run whose setup could not be prepared."""
        run = self._load_run(run_id)
        self._emit(run_id, "run.created", RunCreated(request_text=run["request_text"]))
        self._decide_and_finish(run_id, decision)

    # Helpers -----------------------------------------------------------------------

    def _load_run(self, run_id: str) -> dict[str, Any]:
        with db.connect() as conn:
            run = conn.execute("select * from runs where id = %s", (run_id,)).fetchone()
        if run is None:
            raise LookupError(f"run {run_id} not found")
        return dict(run)

    def _emit(self, run_id: str, type_name: str, payload: Any) -> None:
        events.emit(run_id, type_name, payload)

    def _set_status(self, run_id: str, status: str) -> None:
        with db.connect() as conn:
            conn.execute("update runs set status = %s where id = %s and outcome is null", (status, run_id))
        self._emit(run_id, "run.status", RunStatusPayload(status=status))  # type: ignore[arg-type]

    def _decide_and_finish(self, run_id: str, decision: Decision) -> None:
        self._emit(
            run_id,
            "policy.decided",
            PolicyDecided(
                decision=decision.decision, rule=decision.rule, detail=decision.detail, remedy=decision.remedy
            ),
        )
        outcome = decision.decision if decision.decision != "ALLOW" else "SUCCESS"
        self._finish(run_id, outcome, decision.remedy, [])

    def _finish(self, run_id: str, outcome: str, remedy: str | None, invariants_expected: list[str]) -> None:
        with db.connect() as conn:
            existing = conn.execute("select outcome from runs where id = %s", (run_id,)).fetchone()
        if existing is None or existing["outcome"]:
            return
        payload = {
            "kind": "run_outcome",
            "run_id": run_id,
            "outcome": outcome,
            "remedy": remedy,
            "invariants_expected": list(invariants_expected),
        }
        _, _, head = ledger.append_chain(run_id, payload)
        signature = ledger.sign_head(head)
        with db.connect() as conn:
            conn.execute(
                """update runs set outcome = %s, remedy = %s, status = %s, finished_at = now(),
                     invariants_expected = %s where id = %s and outcome is null""",
                (outcome, remedy, STATUS_FOR_OUTCOME[outcome], Jsonb(list(invariants_expected)), run_id),
            )
        self._emit(
            run_id,
            "run.outcome",
            RunOutcomePayload(
                outcome=outcome,  # type: ignore[arg-type]
                remedy=remedy,
                chain_head=head,
                signature=signature,
                public_key=ledger.public_key_hex(),
                invariants_expected=list(invariants_expected),
            ),
        )

    def _adapters_for(self, fault: str | None) -> AdapterSet:
        if fault and self.adapters_for_fault is not None:
            scoped = self.adapters_for_fault(fault)
            # Approvals always go through the long-lived Slack connection, never a per-run copy.
            scoped.approval = self.adapters.approval
            return scoped
        return self.adapters

    def _require_apps(self, run_id: str, adapters: AdapterSet) -> bool:
        missing = adapters.missing_apps()
        if (
            not missing
            and adapters.stripe is not None
            and adapters.notion is not None
            and adapters.airtable is not None
        ):
            return True
        names = ", ".join(name.capitalize() for name in missing) or "An app"
        detail = f"{names} {'is' if len(missing) == 1 else 'are'} not configured on this backend."
        if adapters.errors:
            detail += " " + " ".join(adapters.errors.values())
        self._decide_and_finish(
            run_id,
            Decision(
                "NEEDS_HUMAN",
                "apps_not_configured",
                detail,
                f"Set the credentials for {names} on the backend and restart it.",
            ),
        )
        return False

    def _read_plans(self, run_id: str, adapters: AdapterSet) -> PlanLists | None:
        assert adapters.stripe and adapters.notion and adapters.airtable
        try:
            return adapters.stripe.list_plans(), adapters.notion.list_plans(), adapters.airtable.list_plans()
        except AdapterRefusal as refusal:
            self._decide_and_finish(run_id, Decision("NEEDS_HUMAN", "app_access", refusal.reason, refusal.remedy))
        except AdapterFault as fault:
            self._decide_and_finish(
                run_id, Decision("NEEDS_HUMAN", "app_unreachable", str(fault), "Retry the request in a minute.")
            )
        return None

    def _record_resolution(self, run_id: str, resolution: resolver.Resolution) -> None:
        with db.connect() as conn:
            conn.execute(
                """insert into entity_resolution (run_id, plan_key, stripe_product_id, stripe_price_id, notion_page_id,
                     airtable_record_id, confidence, decided_by, candidates) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    run_id,
                    resolution.plan_key,
                    resolution.stripe.external_id if resolution.stripe else None,
                    resolution.stripe.price_id if resolution.stripe else None,
                    resolution.notion.external_id if resolution.notion else None,
                    resolution.airtable.external_id if resolution.airtable else None,
                    resolution.confidence,
                    resolution.decided_by,
                    Jsonb(resolution.candidates),
                ),
            )
        self._emit(
            run_id,
            "resolve.completed",
            ResolveCompleted(
                plan_key=resolution.plan_key,
                stripe_product_id=resolution.stripe.external_id if resolution.stripe else None,
                stripe_price_id=resolution.stripe.price_id if resolution.stripe else None,
                notion_page_id=resolution.notion.external_id if resolution.notion else None,
                airtable_record_id=resolution.airtable.external_id if resolution.airtable else None,
                confidence=resolution.confidence,
                decided_by=resolution.decided_by,  # type: ignore[arg-type]
                candidates=[
                    Candidate(app=str(c["app"]), label=str(c["label"]), score=int(float(str(c["score"]))))
                    for c in resolution.candidates
                ],
            ),
        )

    def _out_of_scope(self, run_id: str, run: dict[str, Any], resolution: resolver.Resolution) -> bool:
        """Sandbox and heal runs carry plan_scope. A run that resolves to any other plan is refused before a write."""
        scope = run.get("plan_scope")
        if not scope or resolver.key_of(resolution.plan_key or "") == resolver.key_of(scope):
            return False
        self._decide_and_finish(
            run_id,
            Decision(
                "REFUSED",
                "sandbox_plan_scope",
                f"This run may only change the plan '{scope}', but the request resolved to '{resolution.plan_key}'.",
                f"Name the {scope} plan in the request. A scoped run never changes another plan.",
            ),
        )
        return True

    def _under_plan_lock(self, run_id: str, plan_key: str, currency: str, body: Callable[[], None]) -> bool:
        """Runs body while holding the per plan and currency advisory lock. A second run is refused cleanly."""
        lock_key = f"plan:{plan_key}:{currency}"
        lock_conn = db.dedicated()
        try:
            got = lock_conn.execute("select pg_try_advisory_lock(hashtext(%s)) as got", (lock_key,)).fetchone()
            if not got or not got["got"]:
                self._decide_and_finish(
                    run_id,
                    Decision(
                        "REFUSED",
                        "concurrent_run",
                        f"Another run is already changing {plan_key} in {currency.upper()}.",
                        "A run is already in progress for this plan; retry after it completes.",
                    ),
                )
                return False
            try:
                body()
            finally:
                lock_conn.execute("select pg_advisory_unlock(hashtext(%s))", (lock_key,))
            return True
        finally:
            lock_conn.close()

    def _finish_unapproved(self, run_id: str, approval: str) -> None:
        if approval == "DENIED":
            self._finish(
                run_id, "REFUSED", "The approver denied this change. Submit a new request if it should proceed.", []
            )
        elif approval == "EXPIRED":
            self._finish(
                run_id,
                "NEEDS_HUMAN",
                "Nobody approved within the time limit. Submit the request again and approve it in Slack.",
                [],
            )
        else:
            self._finish(run_id, "NEEDS_HUMAN", approval, [])

    # The run -----------------------------------------------------------------------

    def _execute(self, run_id: str) -> None:
        run = self._load_run(run_id)
        self._emit(run_id, "run.created", RunCreated(request_text=run["request_text"]))

        parsed = intent_mod.parse(run["request_text"], self.settings.anthropic_api_key, self.settings.anthropic_model)
        if parsed.kind == "unparsed":
            self._decide_and_finish(run_id, Decision("NEEDS_HUMAN", "intent_unparsed", parsed.detail, UNPARSED_REMEDY))
            return
        if parsed.kind == "edit_in_place":
            self._decide_and_finish(run_id, policy.refuse_edit_in_place())
            return
        if parsed.kind == "sync_from_derived":
            self._decide_and_finish(run_id, policy.refuse_direction())
            return
        assert parsed.amount is not None and parsed.interval is not None and parsed.plan_hint is not None
        target: Money = parsed.amount
        interval = parsed.interval
        self._emit(
            run_id,
            "intent.parsed",
            IntentParsed(
                plan_hint=parsed.plan_hint,
                new_amount=MoneyModel(minor_units=target.minor_units, currency=target.currency),
                interval=interval,
            ),
        )

        adapters = self._adapters_for(run["scenario"])
        if not self._require_apps(run_id, adapters):
            return
        plans = self._read_plans(run_id, adapters)
        if plans is None:
            return

        resolution = resolver.resolve(parsed.plan_hint, target.currency, interval, *plans)
        self._record_resolution(run_id, resolution)
        if not resolution.resolved:
            self._decide_and_finish(
                run_id,
                Decision("NEEDS_HUMAN", "plan_resolution", resolution.detail, resolution.remedy or resolver.REMEDY),
            )
            return
        if self._out_of_scope(run_id, run, resolution):
            return
        assert resolution.stripe and resolution.notion and resolution.airtable and resolution.plan_key
        self._under_plan_lock(
            run_id,
            resolution.plan_key,
            target.currency,
            lambda: self._locked_run(run_id, run, adapters, resolution, target, interval),
        )

    def _locked_run(
        self,
        run_id: str,
        run: dict[str, Any],
        adapters: AdapterSet,
        resolution: resolver.Resolution,
        target: Money,
        interval: Any,
    ) -> None:
        stripe, notion, airtable = adapters.stripe, adapters.notion, adapters.airtable
        assert stripe and notion and airtable and resolution.stripe and resolution.notion and resolution.airtable
        plan_key = resolution.plan_key or ""
        s, n, a = resolution.stripe, resolution.notion, resolution.airtable
        with db.connect() as conn:
            conn.execute(
                "update runs set plan_key = %s, currency = %s, interval = %s where id = %s",
                (plan_key, target.currency, interval, run_id),
            )

        locked_in = "Notion" if n.locked else "Airtable" if a.locked else None
        old = s.price
        decision = policy.evaluate(
            policy.PolicyContext(
                plan_key=plan_key,
                currency=target.currency,
                new_minor=target.minor_units,
                old_minor=old.minor_units if old else None,
                match_confidence=resolution.confidence,
                locked_in=locked_in,
            )
        )
        if not decision.allowed:
            self._decide_and_finish(run_id, decision)
            return

        expected = list(verifier.INVARIANTS_EXPECTED)
        if old == target and n.price == target and a.price == target:
            self._emit(
                run_id,
                "policy.decided",
                PolicyDecided(
                    decision="ALLOW",
                    rule="already_in_effect",
                    detail=f"{s.label} already reads {format_money(target)} in Stripe, Notion and Airtable, so nothing is written.",
                    remedy=None,
                ),
            )
            self._verify_and_finish(run_id, adapters, resolution, target, old, interval, locked_in, None, expected)
            return
        self._emit(
            run_id,
            "policy.decided",
            PolicyDecided(decision="ALLOW", rule=decision.rule, detail=decision.detail, remedy=None),
        )

        args = {
            "plan_key": plan_key,
            "currency": target.currency,
            "interval": interval,
            "stripe_product_id": s.external_id,
            "old_price_id": s.price_id,
            "old_minor_units": old.minor_units if old else None,
            "new_minor_units": target.minor_units,
            "notion_page_id": n.external_id,
            "airtable_record_id": a.external_id,
        }
        args_hash = ledger.hash_args(args)
        summary = (
            f"Change {s.label} ({interval}) from {format_money(old) if old else 'no current price'} to "
            f"{format_money(target)} in Stripe, Notion and Airtable."
        )
        approval = self._await_approval(run_id, run["approval_mode"], summary, args_hash)
        if approval != "APPROVED":
            self._finish_unapproved(run_id, approval)
            return

        version = run["change_key"] or f"{target.currency}-{interval}-{target.minor_units}"

        def key(step: str) -> str:
            return f"pq:{plan_key}:{version}:{step}"

        lookup_key = lookup_key_for(plan_key, target.currency, interval)
        create_key = key("create_price")
        failure: StepFailed | None = None
        try:
            new_price_id = self._step(
                run_id,
                1,
                "stripe",
                "create_price",
                create_key,
                {**args, "lookup_key": lookup_key},
                lambda k: stripe.create_price(s.external_id, target, interval, lookup_key, k),
                # Recovery looks for the price this key created. A same-amount price from anywhere else is not ours.
                lambda: stripe.find_created_price(s.external_id, target, interval, lookup_key, create_key),
            )
            self._step(
                run_id,
                2,
                "stripe",
                "set_default_price",
                key("set_default"),
                {"stripe_product_id": s.external_id, "price_id": new_price_id},
                lambda k: stripe.set_default_price(s.external_id, new_price_id, k),
                lambda: s.external_id if stripe.read_back(s.external_id).value == target else None,
            )
            if s.price_id and s.price_id != new_price_id and old is not None and old != target:
                old_price_id = s.price_id
                self._step(
                    run_id,
                    3,
                    "stripe",
                    "archive_price",
                    key("archive_old"),
                    {"price_id": old_price_id},
                    lambda k: stripe.archive_price(old_price_id, k),
                    # Proof reads this exact price. Another active price at the old amount is not evidence either way.
                    lambda: old_price_id if stripe.price_is_archived(old_price_id) else None,
                )
            self._step(
                run_id,
                4,
                "notion",
                "update_price",
                key("notion"),
                {"notion_page_id": n.external_id, "new_minor_units": target.minor_units, "currency": target.currency},
                _derived_write(notion, n.external_id, target),
                _derived_landed(notion, n.external_id, target),
            )
            self._step(
                run_id,
                5,
                "airtable",
                "upsert_price",
                key("airtable"),
                {
                    "airtable_record_id": a.external_id,
                    "new_minor_units": target.minor_units,
                    "currency": target.currency,
                },
                _derived_write(airtable, a.external_id, target),
                _derived_landed(airtable, a.external_id, target),
            )
        except StepFailed as exc:
            failure = exc
        self._verify_and_finish(run_id, adapters, resolution, target, old, interval, locked_in, failure, expected)

    # The heal run ------------------------------------------------------------------

    def _execute_heal(self, run_id: str, plan_key: str) -> list[str]:
        run = self._load_run(run_id)
        self._emit(run_id, "run.created", RunCreated(request_text=run["request_text"]))
        adapters = self.adapters
        if not self._require_apps(run_id, adapters):
            return []
        plans = self._read_plans(run_id, adapters)
        if plans is None:
            return []
        stripe_plans, notion_plans, airtable_plans = plans
        owners = [
            plan
            for plan in stripe_plans
            if plan.pq_plan_id and resolver.key_of(plan.pq_plan_id) == resolver.key_of(plan_key) and plan.price
        ]
        if not owners or owners[0].price is None:
            self._decide_and_finish(
                run_id,
                Decision(
                    "NEEDS_HUMAN",
                    "plan_resolution",
                    f"No Stripe product with a price carries pq_plan_id '{plan_key}', so there is no price to follow.",
                    resolver.REMEDY,
                ),
            )
            return []
        source_price = owners[0].price
        resolution = resolver.resolve(
            plan_key, source_price.currency, owners[0].interval or "month", stripe_plans, notion_plans, airtable_plans
        )
        self._record_resolution(run_id, resolution)
        if not resolution.resolved:
            self._decide_and_finish(
                run_id,
                Decision("NEEDS_HUMAN", "plan_resolution", resolution.detail, resolution.remedy or resolver.REMEDY),
            )
            return []
        if self._out_of_scope(run_id, run, resolution):
            return []
        assert resolution.stripe and resolution.stripe.price and resolution.plan_key
        target = resolution.stripe.price
        interval = resolution.stripe.interval or "month"
        healed: list[str] = []

        def body() -> None:
            healed.extend(self._locked_heal(run_id, run, adapters, resolution, target, interval))

        self._under_plan_lock(run_id, resolution.plan_key, target.currency, body)
        return healed

    def _locked_heal(
        self,
        run_id: str,
        run: dict[str, Any],
        adapters: AdapterSet,
        resolution: resolver.Resolution,
        target: Money,
        interval: Any,
    ) -> list[str]:
        notion, airtable = adapters.notion, adapters.airtable
        assert notion and airtable and resolution.stripe and resolution.notion and resolution.airtable
        plan_key = resolution.plan_key or ""
        s, n, a = resolution.stripe, resolution.notion, resolution.airtable
        with db.connect() as conn:
            conn.execute(
                "update runs set plan_key = %s, currency = %s, interval = %s where id = %s",
                (plan_key, target.currency, interval, run_id),
            )
        locked_in = "Notion" if n.locked else "Airtable" if a.locked else None
        decision = policy.evaluate(
            policy.PolicyContext(
                plan_key=plan_key,
                currency=target.currency,
                new_minor=target.minor_units,
                old_minor=target.minor_units,
                match_confidence=resolution.confidence,
                locked_in=locked_in,
            )
        )
        if not decision.allowed:
            self._decide_and_finish(run_id, decision)
            return []

        expected = list(verifier.INVARIANTS_EXPECTED)
        drifted: list[tuple[str, PlanRecord, DerivedPort]] = [
            (app, record, port)
            for app, record, port in (("notion", n, notion), ("airtable", a, airtable))
            if record.price != target
        ]
        if not drifted:
            self._emit(
                run_id,
                "policy.decided",
                PolicyDecided(
                    decision="ALLOW",
                    rule="already_in_effect",
                    detail=f"Notion and Airtable already read {format_money(target)}, the Stripe price, so nothing is written.",
                    remedy=None,
                ),
            )
            self._verify_and_finish(run_id, adapters, resolution, target, target, interval, locked_in, None, expected)
            return []

        shown = "; ".join(
            f"{app.capitalize()} reads {format_money(record.price) if record.price else 'nothing readable'}"
            for app, record, _ in drifted
        )
        names = " and ".join(app.capitalize() for app, _, _ in drifted)
        self._emit(
            run_id,
            "policy.decided",
            PolicyDecided(
                decision="ALLOW",
                rule="heal_derived",
                detail=f"{shown}; Stripe reads {format_money(target)}. Only {names} will be written; Stripe is not.",
                remedy=None,
            ),
        )
        args = {
            "plan_key": plan_key,
            "currency": target.currency,
            "interval": interval,
            "stripe_product_id": s.external_id,
            "stripe_price_id": s.price_id,
            "target_minor_units": target.minor_units,
            "notion_page_id": n.external_id,
            "airtable_record_id": a.external_id,
            "heal_apps": [app for app, _, _ in drifted],
        }
        args_hash = ledger.hash_args(args)
        summary = f"Heal {s.label}: write the Stripe price {format_money(target)} to {names}. Stripe is not written."
        approval = self._await_approval(run_id, run["approval_mode"], summary, args_hash)
        if approval != "APPROVED":
            self._finish_unapproved(run_id, approval)
            return []

        version = f"heal-{target.currency}-{target.minor_units}-{run_id[:8]}"
        failure: StepFailed | None = None
        try:
            for step_no, (app, record, port) in enumerate(drifted, start=1):
                id_field = "notion_page_id" if app == "notion" else "airtable_record_id"
                self._step(
                    run_id,
                    step_no,
                    app,
                    "update_price" if app == "notion" else "upsert_price",
                    f"pq:{plan_key}:{version}:{app}",
                    {id_field: record.external_id, "new_minor_units": target.minor_units, "currency": target.currency},
                    _derived_write(port, record.external_id, target),
                    _derived_landed(port, record.external_id, target),
                )
        except StepFailed as exc:
            failure = exc
        outcome = self._verify_and_finish(
            run_id, adapters, resolution, target, target, interval, locked_in, failure, expected
        )
        return [app for app, _, _ in drifted] if outcome == "SUCCESS" else []

    # Approval, steps and verification ----------------------------------------------

    def _await_approval(self, run_id: str, requested_mode: str, summary: str, args_hash: str) -> str:
        """Blocks until a person decides or the approval expires. Returns APPROVED, DENIED, EXPIRED, or a remedy."""
        approval_port = self.adapters.approval
        preapproved = requested_mode == PREAPPROVED_MODE
        mode = "operator" if preapproved else requested_mode
        if mode == "slack" and (approval_port is None or not approval_port.connected()):
            mode = "operator" if self.settings.pq_operator_token else ""
        if not mode:
            return "No approval channel is available. Connect the Slack app, or set PQ_OPERATOR_TOKEN on the backend."
        row = approvals.create(run_id, "migrate_price", summary, args_hash, mode, self.settings.pq_approval_ttl_seconds)
        posted: ApprovalPosted | None = None
        if mode == "slack" and approval_port is not None:
            try:
                posted = approval_port.post_request(
                    ApprovalRequest(run_id=run_id, summary=summary, args_hash=args_hash, expires_at=row["expires_at"])
                )
                approvals.set_posted(run_id, posted.channel, posted.ts)
            except (AdapterFault, AdapterRefusal) as exc:
                approvals.decide(run_id, "deny", "approval could not be posted", None)
                return f"The Slack approval could not be posted: {exc}. Check the Slack app and channel, then retry."
        self._emit(
            run_id,
            "approval.requested",
            ApprovalRequested(
                summary=summary,
                args_hash=args_hash,
                slack_channel=posted.channel if posted else None,
                slack_ts=posted.ts if posted else None,
                expires_at=events.iso(row["expires_at"]),
                mode=mode,  # type: ignore[arg-type]
            ),
        )
        self._set_status(run_id, "awaiting_human")
        if mode == "sandbox_auto":
            approvals.decide(run_id, "approve", SANDBOX_APPROVER, args_hash)
        elif preapproved:
            approvals.decide(run_id, "approve", HEAL_APPROVER, args_hash)

        while True:
            current = approvals.get(run_id)
            if current is None:
                return "The approval record disappeared. Submit the request again."
            if current["status"] != "PENDING":
                break
            if current["expires_at"] <= datetime.now(UTC):
                approvals.expire_due()
                continue
            self.sleep(self.settings.pq_approval_poll_seconds)

        self._emit(
            run_id,
            "approval.decided",
            ApprovalDecided(
                decision=current["status"],
                approver_display=current["approver_display"],
                decided_at=events.iso(current["decided_at"]) if current["decided_at"] else None,
                mode=mode,  # type: ignore[arg-type]
            ),
        )
        if posted is not None and approval_port is not None:
            try:
                approval_port.post_outcome(posted, current["status"], current["approver_display"])
            except (AdapterFault, AdapterRefusal) as exc:
                log.warning("could not update the Slack approval message: %s", exc)
        self._set_status(run_id, "running")
        return str(current["status"])

    def _step(
        self,
        run_id: str,
        step_no: int,
        app: str,
        action: str,
        idempotency_key: str,
        args: dict[str, Any],
        call: Callable[[str], WriteResult],
        recover: Callable[[], str | None],
    ) -> str:
        """One external write: pending row first, then the call, read back on any ambiguous failure, and a retry
        with the same idempotency key only when the read-back shows the write did not land."""
        row = ledger.pending(run_id, step_no, app, action, idempotency_key, args, {"app": app, "action": action})
        self._emit(
            run_id,
            "ledger.pending",
            LedgerPending(
                ledger_id=row.id,
                step_no=step_no,
                app=app,
                action=action,
                idempotency_key=idempotency_key,
                args_hash=row.args_hash,
            ),
        )
        external_id: str | None = row.external_object_id if row.state == "completed" else None
        attempts = 0
        while external_id is None:
            attempts += 1
            try:
                external_id = call(idempotency_key).external_object_id
            except AdapterRefusal as refusal:
                ledger.fail(row, "REFUSED", refusal.remedy)
                raise StepFailed("REFUSED", refusal.reason, refusal.remedy) from refusal
            except AdapterFault as fault:
                self._emit(
                    run_id,
                    "adapter.fault",
                    AdapterFaultPayload(
                        ledger_id=row.id, call_site=fault.call_site, kind=fault.kind, injected=fault.injected
                    ),
                )
                try:
                    landed = recover()
                except (AdapterFault, AdapterRefusal):
                    landed = None
                self._emit(
                    run_id,
                    "readback.recovery",
                    ReadbackRecovery(
                        ledger_id=row.id,
                        call_site=fault.call_site,
                        found_landed=landed is not None,
                        external_object_id=landed,
                    ),
                )
                if landed is not None:
                    external_id = landed
                    break
                if attempts >= self.settings.pq_max_step_attempts:
                    remedy = (
                        f"{app.capitalize()} {action.replace('_', ' ')} did not confirm after {attempts} attempts. "
                        "Re-run the request with the same change key once the app is reachable."
                    )
                    ledger.fail(row, "PARTIAL", remedy)
                    raise StepFailed("PARTIAL", f"{app} {action} did not land", remedy) from fault
                if fault.kind == "rate_limit":
                    self.sleep(self.settings.pq_rate_limit_wait_seconds)
                elif fault.kind == "conflict_409":
                    # A concurrent request holds the key: wait and read back instead of racing it.
                    self.sleep(min(2.0, self.settings.pq_rate_limit_wait_seconds))
        prev_hash, entry_hash = ledger.complete(row, external_id)
        self._emit(
            run_id,
            "ledger.completed",
            LedgerCompleted(
                ledger_id=row.id,
                step_no=step_no,
                external_object_id=external_id,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            ),
        )
        return external_id

    def _verify_and_finish(
        self,
        run_id: str,
        adapters: AdapterSet,
        resolution: resolver.Resolution,
        target: Money,
        old: Money | None,
        interval: Any,
        locked_in: str | None,
        failure: StepFailed | None,
        expected: list[str],
    ) -> str:
        assert adapters.stripe and adapters.notion and adapters.airtable
        assert resolution.stripe and resolution.notion and resolution.airtable
        result = verifier.verify(
            target=target,
            old_amount=old,
            interval=interval,
            stripe=adapters.stripe,
            notion=adapters.notion,
            airtable=adapters.airtable,
            product_id=resolution.stripe.external_id,
            page_id=resolution.notion.external_id,
            record_id=resolution.airtable.external_id,
            locked_in=locked_in,
            old_price_id=resolution.stripe.price_id,
        )
        source_ids = {
            "stripe": resolution.stripe.external_id,
            "notion": resolution.notion.external_id,
            "airtable": resolution.airtable.external_id,
        }
        for app, readback in result.readbacks.items():
            if readback is not None:
                payload = ReadbackResultPayload(
                    app=app,
                    value=MoneyModel(minor_units=readback.value.minor_units, currency=readback.value.currency)
                    if readback.value
                    else None,
                    raw_value=readback.raw_value,
                    fresh=True,
                    read_at=events.iso(readback.read_at),
                    source_id=readback.source_id,
                )
            else:
                # The read failed: say so with fresh=false rather than presenting an old value as current.
                payload = ReadbackResultPayload(
                    app=app,
                    value=None,
                    raw_value=None,
                    fresh=False,
                    read_at=events.now_iso(),
                    source_id=source_ids[app],
                )
            self._emit(run_id, "readback.result", payload)
        for check in result.invariants:
            self._emit(
                run_id,
                "invariant.result",
                InvariantResultPayload(name=check.name, ok=check.ok, detail=check.detail, outcome=check.outcome),  # type: ignore[arg-type]
            )
        outcomes = [result.verdict] + ([failure.outcome] if failure else [])
        outcome = verifier.worst(outcomes)
        remedy = failure.remedy if failure else result.remedy
        self._finish(run_id, outcome, remedy, expected)
        return outcome
