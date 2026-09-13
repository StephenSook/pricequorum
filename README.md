# PriceQuorum

An agent that changes a SaaS plan's published price once, correctly, across Stripe, Notion, and Airtable, gated by a human approval in Slack, and proves it by reading every system back.

| | |
|---|---|
| **Demo video (80 s)** | https://pricequorum-web.vercel.app/demo/PriceQuorum_Demo.mp4 |
| **Live web app** | https://pricequorum-web.vercel.app |
| **Three-minute judge tour** | https://pricequorum-web.vercel.app/judges |
| **Backend health** | https://pricequorum-api.onrender.com/api/health |
| **Android APK** | [release v1.0.0](https://github.com/StephenSook/pricequorum/releases/tag/v1.0.0) |
| **iOS** | TestFlight build 2, public link https://testflight.apple.com/join/7HthxaHv opens once Apple's beta review approves it |

## Status at submission (read this first)

Built during the Multi-App AI Agent Hackathon, September 13, 2026.

- **Deployed:** the web app (Vercel), the FastAPI backend and its Postgres database (Render), and the mobile app (TestFlight internal testing, signed Android APK).
- **Tested:** 169 backend tests and 81 web unit tests pass; CI is green on every job for the submitted commit.
- **Not connected yet:** the Stripe, Notion, Airtable and Slack credentials were not configured on the deployed backend in time. `/api/health` says so by name, and every page that needs vendor data shows that state instead of placeholder numbers. No run has been made against the real vendor accounts, and no eval number against real apps is claimed anywhere in this repository or the video.

## 1. Project overview

Stripe does not let you edit a price. Its documentation: "After you create a price, you can only update its metadata, nickname, and active fields." So one price change is a migration: a new Stripe Price, the lookup key moved to it, the default switched, the old one archived. Then the Notion pricing page and the Airtable sales catalogue have to follow. Miss one and a customer gets quoted the wrong number.

PriceQuorum takes the change in plain words ("Raise the Pro plan to $25 a month") and:

1. **Resolves** the plan across the three apps (exact `pq_plan_id` first, a fuzzy match below the threshold goes to a person).
2. **Checks policy** in `backend/pricequorum/policy.py`, a file with no model import, so text read from an app can never talk its way past a rule. Every refusal returns a remedy.
3. **Waits for approval** in Slack before any write.
4. **Writes each app once**, recording a pending ledger row before every call and using a deterministic idempotency key. If a call times out after Stripe commits, it reads Stripe back instead of retrying blind.
5. **Verifies** with fresh reads from all three apps, compared in integer minor units, and reports SUCCESS only when they all agree.
6. **Records** every step in a hash-chained ledger (SHA-256 over the RFC 8785 canonical payload) whose head is signed with Ed25519. `/verify` recomputes the chain in your own browser.

## 2. External apps used

| App | Role | Code |
|---|---|---|
| Stripe (test mode only, a live key is refused) | Authoritative billing: new Price, transfer lookup key, move default, archive old | `backend/pricequorum/adapters/stripe_adapter.py` |
| Notion (API `2025-09-03`, data sources) | Derived public pricing page, follows Stripe | `backend/pricequorum/adapters/notion_adapter.py` |
| Airtable | Derived SKU catalogue, upsert on `pq_plan_id` | `backend/pricequorum/adapters/airtable_adapter.py` |
| Slack (Socket Mode) | Human approval gate before any consequential write | `backend/pricequorum/adapters/slack_approval.py` |

All four sit behind one seam, `backend/pricequorum/ports.py`, so the run loop never imports a vendor SDK.

## 3. Setup

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22, Postgres.

**Backend**

```
cd backend
uv sync
export DATABASE_URL=postgresql://postgres@localhost:5432/pricequorum
uv run uvicorn pricequorum.api.app:app --reload
```

Vendor credentials use the names in `.env.example` and `backend/render.yaml`. Without them the API still starts and `/api/health` names each app that is not configured. `backend/scripts/seed.py` and `backend/scripts/reset.py` create and reset the demo plan in the three apps; `backend/scripts/live_check.py` checks each connection.

**Web**

```
cd web
npm ci
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

**Deploy:** `backend/render.yaml` describes the Render web service (Docker) and Postgres. The web app deploys to Vercel from `web/`.

## 4. Reliability testing

**How it is tested**

| What | How | Where |
|---|---|---|
| Backend correctness | `ruff format --check`, `ruff check`, `mypy`, `pytest` against a real Postgres service, OpenAPI contract check. 169 tests pass. | `.github/workflows/backend.yml`, `backend/tests/` |
| Failure scenarios | 20 scenario files, one per failure the spec names: timeout after commit, half-landed write, idempotency 409, rate limit 429, stale read, prompt injection, locked record, forbidden edit, ambiguous name, two currencies, float precision, concurrent runs, chain tamper, approval denied and expired, and more. A test asserts all 20 load and that each runnable one states an outcome and an end state. | `backend/evals/scenarios/`, `backend/tests/evals/` |
| Fault injection | Faults raised after the real request dispatches, so recovery is tested against a write that may have landed | `backend/pricequorum/adapters/faults.py` |
| Eval harness | Runs the scenarios, computes a Wilson 95% interval, posts results; `/api/proof` recomputes the headline from the database on every request | `backend/evals/`, `GET /api/proof` |
| Judge sandbox | Seven scenarios a judge can trigger on an isolated plan: happy path, timeout after commit, prompt injection, locked record, chain tamper, concurrent runs, drift | `backend/pricequorum/sandbox.py`, `/break` |
| Ledger verification | Browser verifier tested against hashes computed independently with Python `hashlib` | `web/lib/verify/` |
| Web app | Contract drift check, typecheck, lint, 81 unit tests, production build | `.github/workflows/web.yml` |
| Deployed site | On every push and every 30 minutes: waits for the live build to equal the pushed commit, loads every route on desktop and phone, fails on any console error, failed asset or serious axe (WCAG 2.1 AA) violation | `.github/workflows/deployed-smoke.yml` |
| Mobile | Shared run and ledger logic checked for drift against `web/` in CI | `.github/workflows/mobile.yml` |

**Honesty rules the UI follows:** a run is shown as verified only when it carries its list of expected checks and every check arrived complete and passing; a failed event stream is never shown as finished; an unsigned ledger is never shown green.

**Not yet verified:** the scenarios and eval harness have not been run against real Stripe, Notion, Airtable and Slack accounts, because the vendor credentials were not connected to the deployed backend before the deadline. Every eval page says so rather than showing a number.

## 5. Demo video

80 seconds, built from captures of the deployed site: https://pricequorum-web.vercel.app/demo/PriceQuorum_Demo.mp4

## API

| Route | Purpose |
|---|---|
| `GET /api/health` | Commit, database, and which vendor apps are configured |
| `POST /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/events` | Start a run and follow it over Server-Sent Events with replay |
| `POST /api/runs/{id}/approval` | Operator approval fallback, same resume path as Slack |
| `GET /api/ledger/export`, `POST /api/ledger/verify`, `GET /api/public-key` | Ledger and signature |
| `GET /api/proof`, `GET /api/evals/latest` | Eval results recomputed from the database |
| `POST /api/sandbox/runs`, `GET /api/sandbox/status` | Judge sandbox |
| `GET /api/monitor/events`, `POST /api/monitor/heal` | Drift monitor for Notion and Airtable against Stripe |
| `/mcp/` | MCP server over Streamable HTTP with four tools that call this API |

## Web pages

| Route | What it does |
|---|---|
| `/` | Type a price change and follow the run chapter by chapter |
| `/runs/[id]` | The receipt for one run, rebuilt from its recorded events |
| `/verify` | Recomputes the ledger hash chain and checks the head signature in your browser |
| `/evals` | Scenario pass rate, refusals, duplicate writes prevented, named failures |
| `/break` | Trigger a sandbox scenario built to go wrong in one specific way |
| `/judges` | A short tour that marks each stop live only after the backend answers |

## Repository

- `backend/`: FastAPI service, adapters, ledger, evals, MCP server ([backend/README.md](backend/README.md))
- `web/`: Next.js app (App Router, Tailwind 4, GSAP)
- `mobile/`: Expo app for iOS and Android, sharing the run and ledger logic with `web/`
- `docs/contracts/api.md`: the API and event-stream contract
- `docs/fact-sheet.md`: the only source for numbers used in the video and README
- `PLAN.md`: task status and ownership

License: MIT.
