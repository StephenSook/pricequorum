# Khadim Tasks

Personal task view. Source of truth is PLAN.md (task numbers match). Legend: [ ] not started · [-] in progress · [x] done · [!] blocked

Deadline: **7:00 PM ET submission.** Everything you own must run against the deployed backend before 5:45 PM ET (freeze).

Role: **evaluation suite and judge-facing integrations.** Tylin owns the core loop (adapters, ledger, agent, Slack, verifier). You build on top of it through its public functions and the API, so you rarely need to touch his files.

---

## Lane ownership (edit only these)

- `backend/evals/**`
- `backend/monitor/**`
- `backend/mcp/**`
- `backend/api/routes_sandbox.py`
- `backend/api/routes_proof.py`
- `backend/tests/evals/**`
- `KHADIM_TASKS.md`

Need a change in `backend/adapters/**`, `backend/ledger/**`, `backend/agent/**` or `backend/verifier/**`? Write it under Open Questions in PLAN.md and ping Tylin. Need a change in `web/**`? Ping Stephen.

## Before you start

1. Accept the GitHub invite, clone, read `AGENTS.md`, `PLAN.md` and `docs/contracts/api.md`.
2. Get the backend `.env` values from Tylin over a private channel (never in git).
3. `cd backend && uv sync && uv run pytest -q` must pass on your machine.

## Phase 2 support (until 3:45 PM ET)

- [ ] **3.1a** Eval scenario files: one file per scenario in `backend/evals/scenarios/`, all 20 from the master spec section 14 (`happy_path`, `idempotent_noop`, `ambiguous_name`, `no_conflate`, `two_currency`, `half_landed`, `timeout_after_commit`, `archived_referenced`, `forbidden_edit`, `migrate_needs_approval`, `approval_denied`, `approval_expired`, `prompt_injection`, `locked_record`, `stale_read`, `rate_limit_429`, `concurrent_runs`, `idempotency_409`, `float_precision`, `chain_tamper`). Each file: seed, request, faults, expected outcome, expected end state in minor units.
- [ ] **2.5b** Hand-labeled resolver set: 20 to 40 rows in `backend/evals/labeled_plans.csv` (match or non-match), including Pro USD vs Pro EUR and Pro vs Pro (2023).

## Phase 3 (until 5:45 PM ET)

- [ ] **3.1** Eval harness `backend/evals/run_evals.py`: reset world, run, read back all three systems fresh, compare outcome and end state, write `eval_results`. Report passed/total, per-outcome counts, runs per scenario, Wilson 95% interval, duplicate writes prevented, forbidden actions refused, named failures with explanations. `--ci` mode for GitHub Actions.
- [ ] **3.5** `GET /api/proof` recomputed from the database on each request (shape in the contract).
- [ ] **3.6** Drift monitor: poll Notion and Airtable, compare to Stripe in minor units, emit `drift.detected` / `drift.healed` on `GET /api/monitor/events`; `POST /api/monitor/heal` writes derived surfaces only.
- [ ] **3.7** Judge sandbox `POST /api/sandbox/runs` and `GET /api/sandbox/status`: isolated judge plan, rate limit, reset job, `chain_tamper` on a sandbox copy of the chain only.
- [ ] **3.10** HTTP MCP server with tools `run_price_change`, `get_run`, `verify_chain`, `get_proof`, plus one working `curl` for the README.
- [ ] **3.11** Arga twins spike (30 minute cap). Keep only if a write lands.
- [ ] **3.12** Break each eval gate on purpose (flip an expected outcome, corrupt an expected amount) and confirm the suite goes red, then restore.

## Contracts you own

`GET /api/proof`, `GET /api/evals/latest`, `GET /api/monitor/events`, `POST /api/monitor/heal`, `POST /api/sandbox/runs`, `GET /api/sandbox/status`, `POST /mcp`. Shapes live in `docs/contracts/api.md`; change them only through a PR titled `⚠️ CONTRACT: field, reason` with regenerated `shared/openapi.json`.

## Rules

1. No em-dashes anywhere: code, comments, commits, docs, strings.
2. Stage named paths only. Never `git add -A`.
3. CI gates run bare. A skipped test is a false green.
4. One logical change per commit, pushed right away. Status updates `status: [#] emoji description`, never bundled with code.
5. Money compares as integer minor units only.
6. An eval passes only on a fresh read of every system. Never assert on model text.
7. Faults you inject are labeled `injected: true` in every event.
8. The repo is public: never paste a key, token or customer detail into a file, commit message or log.
