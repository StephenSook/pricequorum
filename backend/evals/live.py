"""The evaluation harness's contact with real systems: the deployed backend over HTTP, and fresh reads of
Stripe, Notion and Airtable through the adapters. Tests do not import this module's vendor paths.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import stripe

from evals.harness import Observation, Reading, recompute_first_bad, tamper
from evals.scenario import APPS, PLAN_CURRENCY, Scenario
from pricequorum.adapters import build_adapters
from pricequorum.adapters.airtable_adapter import AIRTABLE_API
from pricequorum.adapters.notion_adapter import NOTION_API, NOTION_VERSION
from pricequorum.ports import AdapterFault, AdapterRefusal, Money, PlanRecord

BACKEND_DIR = Path(__file__).resolve().parents[1]
RATE_LIMIT_RETRIES = 3
SETTING_NAMES = (
    "stripe_secret_key",
    "notion_token",
    "notion_data_source_id",
    "airtable_pat",
    "airtable_base_id",
    "airtable_table",
)


class HarnessError(RuntimeError):
    """The harness could not observe a trial. The trial is graded as a failure with this message."""


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


class BackendClient:
    """The deployed backend, reached only through its public HTTP contract."""

    def __init__(
        self,
        base_url: str,
        operator_token: str | None,
        client: httpx.Client | None = None,
        poll_seconds: float = 2.0,
        timeout_seconds: float = 240.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.token = operator_token
        self.client = client or httpx.Client(timeout=60.0)
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds
        self.sleep = sleep
        self.clock = clock

    def _headers(self) -> dict[str, str]:
        return {"X-Operator-Token": self.token} if self.token else {}

    def start_run(self, request_text: str | None, fault: str | None, approval: str) -> str:
        body: dict[str, Any] = {"request_text": request_text}
        if fault:
            body["fault"] = fault
        if approval == "sandbox_auto":
            body["approval_mode"] = "sandbox_auto"
        response = self.client.post(f"{self.base}/api/runs", json=body, headers=self._headers())
        # The backend limits runs per address per minute; the suite waits out the limit rather than failing.
        for _ in range(RATE_LIMIT_RETRIES):
            if response.status_code != 429:
                break
            retry_after = response.headers.get("retry-after", "")
            self.sleep(min(float(retry_after) if retry_after.isdigit() else 30.0, 60.0))
            response = self.client.post(f"{self.base}/api/runs", json=body, headers=self._headers())
        data = _json(response)
        if (
            response.status_code not in (200, 201, 202)
            or not isinstance(data, dict)
            or not isinstance(data.get("run_id"), str)
        ):
            detail = data.get("detail") if isinstance(data, dict) else None
            raise HarnessError(f"POST /api/runs answered {response.status_code}: {detail or 'no run_id returned'}")
        return data["run_id"]

    def events(self, run_id: str) -> list[dict[str, Any]]:
        response = self.client.get(f"{self.base}/api/runs/{run_id}/events.json")
        data = _json(response)
        if response.status_code != 200 or not isinstance(data, list):
            raise HarnessError(f"GET /api/runs/{run_id}/events.json answered {response.status_code}")
        return [event for event in data if isinstance(event, dict)]

    def deny(self, run_id: str) -> None:
        response = self.client.post(
            f"{self.base}/api/runs/{run_id}/approval", json={"decision": "deny"}, headers=self._headers()
        )
        if response.status_code not in (200, 409):
            raise HarnessError(f"POST /api/runs/{run_id}/approval answered {response.status_code}")

    def wait_for_outcome(self, run_id: str, deny_on_request: bool = False) -> tuple[str | None, list[dict[str, Any]]]:
        """Polls the recorded events until run.outcome arrives, denying the approval once if asked."""
        deadline = self.clock() + self.timeout_seconds
        denied = False
        while True:
            events = self.events(run_id)
            if deny_on_request and not denied and any(event.get("type") == "approval.requested" for event in events):
                self.deny(run_id)
                denied = True
            finals = [event for event in events if event.get("type") == "run.outcome"]
            if finals:
                payload = finals[-1].get("payload")
                outcome = payload.get("outcome") if isinstance(payload, dict) else None
                return (outcome if isinstance(outcome, str) else None), events
            if self.clock() > deadline:
                raise HarnessError(f"run {run_id} reported no run.outcome within {self.timeout_seconds:.0f} s")
            self.sleep(self.poll_seconds)

    def ledger_export(self) -> dict[str, Any]:
        response = self.client.get(f"{self.base}/api/ledger/export")
        data = _json(response)
        if response.status_code != 200 or not isinstance(data, dict):
            raise HarnessError(f"GET /api/ledger/export answered {response.status_code}")
        return data

    def ledger_verify(self) -> dict[str, Any]:
        response = self.client.post(f"{self.base}/api/ledger/verify")
        data = _json(response)
        if response.status_code != 200 or not isinstance(data, dict):
            raise HarnessError(f"POST /api/ledger/verify answered {response.status_code}")
        return data

    def post_results(self, report: dict[str, Any]) -> tuple[int, str]:
        response = self.client.post(f"{self.base}/api/evals/results", json=report, headers=self._headers())
        data = _json(response)
        detail = data.get("detail") if isinstance(data, dict) else ""
        return response.status_code, str(detail or "")


class EnvSettings:
    """The settings object build_adapters expects, read from environment variables."""

    def __init__(self, environ: Mapping[str, str]) -> None:
        for name in SETTING_NAMES:
            setattr(self, name, (environ.get(name.upper()) or "").strip() or None)


class VendorWorld:
    """Reset, seed and read back Stripe, Notion and Airtable for one trial."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self.environ = dict(environ if environ is not None else os.environ)
        self.settings = EnvSettings(self.environ)
        self.adapters = build_adapters(self.settings)
        missing = [app for app in APPS if getattr(self.adapters, app) is None]
        if missing:
            raise HarnessError(f"vendor credentials missing for {', '.join(missing)}")
        self.ignored_ids: set[str] = set()
        self.created_products: list[str] = []

    def reset(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/reset.py"], cwd=BACKEND_DIR, env=self.environ, capture_output=True, text=True
        )
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
            raise HarnessError(f"scripts/reset.py failed: {' | '.join(tail)}")

    def plans(self, app: str) -> dict[str, PlanRecord]:
        adapter = getattr(self.adapters, app)
        return {
            record.pq_plan_id: record
            for record in adapter.list_plans()
            if record.pq_plan_id in PLAN_CURRENCY and record.external_id not in self.ignored_ids
        }

    def end_state(self) -> dict[str, dict[str, Reading]]:
        state: dict[str, dict[str, Reading]] = {}
        for app in APPS:
            state[app] = {
                plan: ((record.price.minor_units, record.price.currency) if record.price else (None, None))
                for plan, record in self.plans(app).items()
            }
        return state

    def stripe_price_ids(self) -> dict[str, str | None]:
        return {plan: record.price_id for plan, record in self.plans("stripe").items()}

    def apply_setup(self, actions: tuple[dict[str, Any], ...]) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        for index, action in enumerate(actions):
            plan = action["plan"]
            key = f"pq-eval-setup:{plan}:{index}:{stamp}"
            kind = action["action"]
            if kind == "set_price":
                self._set_price(action["app"], plan, Money(action["minor_units"], PLAN_CURRENCY[plan]), key)
            elif kind == "set_raw_notion_price":
                record = self.plans("notion")[plan]
                self._notion_patch(record.external_id, {"Price": {"number": action["value"]}})
            elif kind == "lock" and action["app"] == "airtable":
                record = self.plans("airtable")[plan]
                self._airtable_patch(record.external_id, {"Locked": True})
            elif kind == "lock":
                record = self.plans("notion")[plan]
                self._notion_patch(record.external_id, {"Locked": {"checkbox": True}})
            elif kind == "duplicate_stripe_product":
                self._duplicate_stripe_product(plan, action["name"], key)

    def _set_price(self, app: str, plan: str, money: Money, key: str) -> None:
        record = self.plans(app)[plan]
        if record.price == money:
            return
        if app == "stripe":
            stripe_port = self.adapters.stripe
            assert stripe_port is not None
            price_id = stripe_port.find_active_price(record.external_id, money, "month") or (
                stripe_port.create_price(
                    record.external_id, money, "month", f"{plan}_{money.currency}_month", key
                ).external_object_id
            )
            stripe_port.set_default_price(record.external_id, price_id, f"{key}:default")
        else:
            getattr(self.adapters, app).write_price(record.external_id, money, key)

    def _notion_patch(self, page_id: str, properties: dict[str, Any]) -> None:
        response = httpx.patch(
            f"{NOTION_API}/pages/{page_id}",
            json={"properties": properties},
            headers={"Authorization": f"Bearer {self.settings.notion_token}", "Notion-Version": NOTION_VERSION},
            timeout=30.0,
        )
        if response.status_code != 200:
            raise HarnessError(f"Notion setup PATCH answered {response.status_code}")

    def _airtable_patch(self, record_id: str, fields: dict[str, Any]) -> None:
        settings = self.settings
        response = httpx.patch(
            f"{AIRTABLE_API}/{settings.airtable_base_id}/{settings.airtable_table}/{record_id}",
            json={"fields": fields},
            headers={"Authorization": f"Bearer {settings.airtable_pat}"},
            timeout=30.0,
        )
        if response.status_code != 200:
            raise HarnessError(f"Airtable setup PATCH answered {response.status_code}")

    def _duplicate_stripe_product(self, plan: str, name: str, key: str) -> None:
        original = self.plans("stripe")[plan]
        amount = original.price.minor_units if original.price else 2000
        client = stripe.StripeClient(str(self.settings.stripe_secret_key))
        product = client.v1.products.create(
            {"name": name, "metadata": {"pq_plan_id": plan}}, {"idempotency_key": f"{key}:product"}
        )
        price = client.v1.prices.create(
            {
                "product": product["id"],
                "unit_amount": amount,
                "currency": PLAN_CURRENCY[plan],
                "recurring": {"interval": "month"},  # type: ignore[typeddict-item]
            },
            {"idempotency_key": f"{key}:price"},
        )
        client.v1.products.update(product["id"], {"default_price": price["id"]})
        self.ignored_ids.add(product["id"])
        self.created_products.append(product["id"])

    def cleanup(self) -> None:
        """Archives products a setup created and clears their plan key, so the next reset sees only the seed."""
        if not self.created_products:
            return
        client = stripe.StripeClient(str(self.settings.stripe_secret_key))
        for product_id in self.created_products:
            client.v1.products.update(product_id, {"active": False, "metadata": {"pq_plan_id": ""}})
        self.created_products.clear()


def run_trial(scenario: Scenario, backend: BackendClient, world: VendorWorld) -> Observation:
    """Resets the world, applies the scenario, runs it through the backend and reads everything back fresh."""
    observation = Observation()
    try:
        if "chain_tamper_detected" in scenario.checks:
            rows = backend.ledger_export().get("rows") or []
            verdict = backend.ledger_verify()
            edited, row_id = tamper(rows) if rows else ([], None)
            observation.chain = {
                "entries": len(rows),
                "server_ok": verdict.get("ok"),
                "untampered_first_bad_id": recompute_first_bad(rows) if rows else None,
                "tampered_row_id": row_id,
                "tampered_first_bad_id": recompute_first_bad(edited) if rows else None,
            }
            return observation

        world.reset()
        world.apply_setup(scenario.setup)
        observation.stripe_price_before = world.stripe_price_ids()
        with ThreadPoolExecutor(max_workers=scenario.concurrent) as pool:
            observation.run_ids = list(
                pool.map(
                    lambda _: backend.start_run(scenario.request_text, scenario.fault, scenario.approval),
                    range(scenario.concurrent),
                )
            )
        deny = scenario.approval == "operator_deny"
        with ThreadPoolExecutor(max_workers=scenario.concurrent) as pool:
            finished = list(pool.map(lambda run_id: backend.wait_for_outcome(run_id, deny), observation.run_ids))
        observation.outcomes = [outcome for outcome, _ in finished]
        observation.events = [events for _, events in finished]
        observation.stripe_price_after = world.stripe_price_ids()
        observation.end_state = world.end_state()
    except (HarnessError, AdapterFault, AdapterRefusal, httpx.HTTPError, stripe.StripeError, KeyError) as error:
        observation.error = f"{type(error).__name__}: {error}"
    finally:
        try:
            world.cleanup()
        except stripe.StripeError as error:
            observation.error = (observation.error or "") + f" cleanup failed: {error}"
    return observation
