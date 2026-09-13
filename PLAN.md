# PRICEQUORUM: Plan & Coordination

> Living status doc for Stephen + Tylin + Khadim. Updated on every task change and pushed to `main`.
> Single source of truth for who is working on what.
> **Atomic commits. Never bundle a status change with code.**

**Project:** An agent that changes a SaaS plan's price once, correctly, across Stripe, Notion and Airtable, gated by a Slack approval, proven by reading every system back, recorded in a hash-chained signed ledger.
**Team:** Stephen (full frontend, submission, demo video, brief, README) · Tylin (backend core loop) · Khadim (evaluation suite and integrations)
**Hackathon:** Multi-App AI Agent Hackathon (Lemma x Comma Capital), Sunday September 13, 2026
**Deadline:** **4:00 PM PT / 7:00 PM ET submission.** Judging 4:00 to 4:40 PT. Keep every host up and warm until 5:00 PM PT.
**Repo:** https://github.com/StephenSook/pricequorum (public, built in the open during the event)
**Spec:** `PriceQuorum_Master_Spec` (shared PDF). API contract: [docs/contracts/api.md](docs/contracts/api.md).

Legend: ✅ done · 🟡 in progress · ⬜ not started · ⛔ blocked · ✂️ cut

**Stale lock TTL: 1 hour.** A 🟡 task without a fresh `HH:MM ET` timestamp in Notes is claimable after pinging the owner.

**All times below are ET. Run `date` before any scope decision. Never trust a mental clock.**

---

## Rubric coverage: the surface that answers each criterion

**Organizers at the opening (12:00 ET) put heavy emphasis on technical execution.** Treat the precision gates below as merge blockers, not goals.

| Criterion | Weight | Surface a judge actually sees | Precision gate (must be true before we claim it) |
|---|---|---|---|
| Technical execution | 30% | Live three-app write path on the deployed site; `backend/adapters/*`; ledger; resolver | Every Stripe call matches spec section 5 exactly (param names, `Idempotency-Key`, 409 vs 429). Integers only for money. Notion `2025-09-03` data sources. Airtable upsert on `pq_plan_id` with JSON numbers. mypy and tsc strict, zero `any` on the contract. Integration tests hit real Stripe test mode, Notion and Airtable, not only mocks. |
| Reliability & evaluation | 25% | `/api/proof` recomputed number; `/evals` board with n, CI and a named failure; `/verify` browser-side chain check; timeout-after-commit recovery on camera | All 20 scenarios run in CI against real test-mode systems. Each eval gate is broken on purpose once and goes red. Browser and server chain verifiers agree on the same head. |
| Usefulness | 20% | Ticket intro states the problem with a sourced frequency number; Slack approval gate; drift detector | Every number shown carries a source in `docs/fact-sheet.md`. The Slack card really pauses the run. |
| Originality | 15% | Verify-and-refuse loop; `backend/agent/policy.py` (the file that does not read English); `/break` judge panel | Every refusal returns a remedy. The injection refusal is enforced in `policy.py`, proven by a test that runs with the model output forced to the malicious value. |
| Demo clarity | 10% | Two-minute video built from real captures of the deployed site; chaptered UI | Every animated beat is driven by a real event. Frames checked at each beat. |

---

## Status Dashboard

### Phase 0: Setup (until 1:15 PM ET)

| # | Component | File(s) | Owner | Status | Deps | Notes |
|---|---|---|---|---|---|---|
| 0.1 | Repo, Tylin and Khadim invited, planning files | `PLAN.md` `AGENTS.md` `*_TASKS.md` `docs/` | Stephen | ✅ | n/a | 13:10 ET |
| 0.2 | Stripe test-mode account + secret key (refuse `sk_live`) | `.env` (never committed) | Tylin | ⬜ | n/a | |
| 0.3 | Notion integration + pricing data source (`Name` title, `pq_plan_id` text, `Price` number, `Currency` select, `Locked` checkbox), shared with the integration | Notion | Tylin | ⬜ | n/a | Invite Stephen as viewer for filming |
| 0.4 | Airtable base, SKU table (`pq_plan_id` unique text, `Price` number, `Currency`, `Locked` checkbox), PAT | Airtable | Tylin | ⬜ | n/a | Invite Stephen for filming |
| 0.5 | Slack app in Socket Mode: bot token, app token (`connections:write`), interactivity on, `#pricequorum-approvals` | Slack | Tylin | ⬜ | n/a | Invite Stephen |
| 0.6 | Supabase Postgres + `DATABASE_URL`; docker-compose Postgres fallback | `docker-compose.yml` | Tylin | ⬜ | n/a | |
| 0.7 | OpenAI key; confirm Python `RunState` serialize/deserialize method names in the Agents SDK HITL guide | `.env` | Tylin | ⬜ | n/a | Spec CRITICAL open item |
| 0.8 | Backend host project (Railway or Render), long-running process for Socket Mode | host | Tylin | ⬜ | n/a | |
| 0.9 | Vercel project `pricequorum-web` created and linked from `web/` only | `web/.vercel` (ignored) `web/vercel.json` | Stephen | ✅ | 1.9 | 13:25 ET. Framework declared in `web/vercel.json` (project was created as "Other" and served only `public/`) |
| 0.10 | Reference site study (screenshots, motion video) | local only | Stephen | ✅ | n/a | 13:00 ET |
| 0.11 | Ledger-paper textures generated and optimized | `web/public/textures/` `web/public/scenes/` | Stephen | ✅ | 1.9 | kie.ai, plus painterly desk scene |

### Phase 1: Contract + foundations (until 2:30 PM ET)

| # | Component | File(s) | Owner | Status | Deps | Notes |
|---|---|---|---|---|---|---|
| 1.1 | Backend scaffold: uv, Python 3.12, FastAPI, `/api/health`, CORS from `PQ_ALLOWED_ORIGINS` | `backend/pyproject.toml` `backend/api/app.py` | Tylin | ⬜ | 0.6 | |
| 1.2 | Migrations: `runs`, `run_events`, `action_ledger`, `paused_runs`, `approvals`, `entity_resolution`, `eval_scenarios`, `eval_results` | `backend/ledger/migrations/` | Tylin | ⬜ | 1.1 | `run_events` persists every SSE envelope |
| 1.3 | Pydantic models for every contract shape + `make openapi` writes `shared/openapi.json` | `backend/api/models.py` `shared/openapi.json` | Tylin | ⬜ | 1.1 | **CONTRACT v1 freeze by 1:45 ET** |
| 1.4 | `money.py`: Decimal from `str()`, ISO exponents, integer compare, tests | `backend/resolver/money.py` | Tylin | ⬜ | 1.1 | No float ever crosses a module boundary |
| 1.5 | Ledger store: pending-before-call, `ON CONFLICT (idempotency_key)`, RFC 8785 chain, `verify_ledger.py`, tests | `backend/ledger/` | Tylin | ⬜ | 1.2 | |
| 1.6 | SSE: persist-then-send, `Last-Event-ID` replay, 15 s heartbeat, `events.json` | `backend/api/sse.py` | Tylin | ⬜ | 1.2 1.3 | SSE response must include CORS headers |
| 1.7 | Seed and reset: Stripe product/prices with `pq_plan_id` metadata and lookup key, Notion rows, Airtable rows | `backend/evals/fixtures/` `Makefile` | Tylin | ⬜ | 0.2 0.3 0.4 | `make seed`, `make reset` idempotent |
| 1.8 | Backend CI: ruff format check, ruff, mypy, pytest, pip-licenses, gitleaks | `.github/workflows/backend.yml` | Tylin | ⬜ | 1.1 | Every gate bare, no pipes |
| 1.9 | Web scaffold: Next.js 16 App Router, Tailwind 4, fonts, tokens, ESLint, Vitest | `web/` | Stephen | ✅ | n/a | tsc and eslint clean |
| 1.10 | Web CI: `openapi-typescript` drift check vs `shared/openapi.json`, tsc, eslint, vitest, build | `.github/workflows/web.yml` | Stephen | ✅ | 1.9 | Green on `cbef0a5`, read from check-runs |
| 1.11 | Generated types, API client, SSE hook with replay, run reducer + tests | `web/lib/api/` | Stephen | 🟡 | 1.3 | 13:25 ET. Client, reducer, replay-safe SSE hook and 15 unit tests done; generated types wait on `shared/openapi.json` |
| 1.12 | Preloader: ribbons, logo clip reveal, min 2 s, waits for assets + `/api/health` | `web/components/motion/Preloader.tsx` | Stephen | ✅ | 1.9 | Visual pass on stills |
| 1.13 | Ticket intro + request form posting `/api/runs` | `web/components/chapters/Ticket.tsx` | Stephen | ✅ | 1.11 | Visual pass on desktop and 390 px stills |
| 1.14 | Motion primitives: reveal group, masked word reveal, word stagger, framing ribbons, CTA, reduced motion | `web/components/motion/` | Stephen | 🟡 | 1.9 | 13:25 ET. In components; reduced motion respected |
| 1.15 | First Vercel deploy + served-bundle check | Vercel | Stephen | ✅ | 0.9 | Live at https://pricequorum-web.vercel.app, 7 served-page checks pass on `61cb695` |

### Phase 2: Full loop live (until 3:45 PM ET)

| # | Component | File(s) | Owner | Status | Deps | Notes |
|---|---|---|---|---|---|---|
| 2.1 | Stripe adapter: create price + `transfer_lookup_key`, `default_price`, archive, read-back, error taxonomy, deterministic idempotency keys | `backend/adapters/stripe_adapter.py` | Tylin | ⬜ | 1.5 | Keys `pq:{plan}:{version}:{step}` |
| 2.2 | Fault injector (`PQ_FAULT`) raising after the real request dispatches | `backend/adapters/faults.py` | Tylin | ⬜ | 2.1 | |
| 2.3 | Notion adapter: data sources API, PATCH number, GET read-back, Locked check | `backend/adapters/notion_adapter.py` | Tylin | ⬜ | 1.5 | |
| 2.4 | Airtable adapter: `performUpsert` on `pq_plan_id`, JSON numbers, 429 backoff 30 s, read-back, Locked check | `backend/adapters/airtable_adapter.py` | Tylin | ⬜ | 1.5 | |
| 2.5 | Resolver: exact `pq_plan_id`, rapidfuzz `token_sort_ratio` fallback, NEEDS_HUMAN below 90, labeled set + P/R/F1 | `backend/resolver/identity.py` `backend/evals/labeled_plans.csv` | Tylin | ⬜ | 1.4 | rapidfuzz (MIT), never thefuzz |
| 2.6 | `policy.py` gates as constants, fail closed; `outcomes.py` enums + remedy strings; one test per rule | `backend/agent/policy.py` `backend/agent/outcomes.py` | Tylin | ⬜ | 1.4 | |
| 2.7 | Agent: Agents SDK, strict structured outputs, datamarked untrusted text, `needs_approval` BEFORE the side effect, RunState in Postgres | `backend/agent/` | Tylin | ⬜ | 2.5 2.6 0.7 | Model proposes, code decides |
| 2.8 | Slack approval: blocks, ack under 3 s then async resume, single-winner UPDATE, TTL sweeper, audit bound to `args_hash`, operator fallback endpoint | `backend/adapters/slack_adapter.py` | Tylin | ⬜ | 2.7 0.5 | |
| 2.9 | Verifier: fresh reads, minor-unit compare, invariant register, worst-class verdict | `backend/verifier/` | Tylin | ⬜ | 2.1 2.3 2.4 | |
| 2.10 | Orchestrator emitting every event in contract order | `backend/api/routes_runs.py` | Tylin | ⬜ | 2.7 2.8 2.9 1.6 | |
| 2.11 | Deploy backend; set `NEXT_PUBLIC_API_BASE_URL` on Vercel | host + Vercel | Tylin + Stephen | ⬜ | 2.10 | |
| 2.12 | Chapter 01 Resolve | `web/components/chapters/Resolve.tsx` | Stephen | 🟡 | 1.11 | Built; unverified until the backend emits real events |
| 2.13 | Chapter 02 Approve (mirrored Slack card, TTL countdown, labels for non-Slack modes) | `web/components/chapters/Approve.tsx` | Stephen | 🟡 | 1.11 | Built; unverified until the backend emits real events |
| 2.14 | Chapter 03 Migrate (ledger sheet stamps, fault banner with `injected` label, read-back recovery) | `web/components/chapters/Migrate.tsx` | Stephen | 🟡 | 1.11 | Built; unverified until the backend emits real events |
| 2.15 | Chapter 04 Verify (three paper columns, invariant bar) | `web/components/chapters/Verify.tsx` | Stephen | 🟡 | 1.11 | Built; unverified until the backend emits real events |
| 2.16 | Receipt outro + `/runs/[id]` permalink | `web/app/runs/[id]/` `web/components/chapters/Receipt.tsx` | Stephen | 🟡 | 1.11 | Receipt and `/runs/[id]` permalink built and live; unverified until the backend emits real events |
| 2.17 | WebGL paper hero shader + static fallback | `web/components/motion/PaperShader.tsx` | Stephen | ⬜ | 1.9 | |

**CHECKPOINT 3:45 PM ET: one real request goes Slack approve, three writes, three read-backs, SUCCESS, rendered in the deployed UI. If not green, both lanes swarm the break before anything in Phase 3.**

### Phase 3: Reliability depth + public demo surfaces (until 5:45 PM ET)

| # | Component | File(s) | Owner | Status | Deps | Notes |
|---|---|---|---|---|---|---|
| 3.1a | Twenty scenario files (seed, request, faults, expected outcome and end state) | `backend/evals/scenarios/` | Khadim | ⬜ | 1.3 | Can start before the loop exists |
| 2.5b | Hand-labeled resolver set, 20 to 40 rows | `backend/evals/labeled_plans.csv` | Khadim | ⬜ | n/a | → Tylin for 2.5 |
| 3.1 | Eval harness + all 20 scenarios from spec section 14, Wilson CI, runs per scenario, named failures, results in DB, `--ci` mode | `backend/evals/` | Khadim | ⬜ | 2.10 3.1a | |
| 3.2 | Concurrency: `pg_try_advisory_xact_lock` + partial unique index | `backend/ledger/` | Tylin | ⬜ | 2.10 | |
| 3.3 | Ed25519 signed head (PyNaCl) + `/api/public-key` | `backend/ledger/signing.py` | Tylin | ⬜ | 1.5 | |
| 3.4 | `/api/ledger/export` + `/api/ledger/verify` | `backend/api/` | Tylin | ⬜ | 3.3 | Chain rule is contract |
| 3.5 | `/api/proof` recomputed from DB | `backend/api/routes_proof.py` | Khadim | ⬜ | 3.1 | |
| 3.6 | Drift monitor + heal (derived surfaces only) + monitor SSE | `backend/monitor/drift.py` | Khadim | ⬜ | 2.9 | |
| 3.7 | Judge sandbox: rate limited, isolated judge plan, reset job, chain tamper on a sandbox copy | `backend/api/routes_sandbox.py` | Khadim | ⬜ | 2.10 3.4 | |
| 3.8 | Crash recovery: restart resumes pending rows by reading back | `backend/ledger/store.py` | Tylin | ⬜ | 2.10 | |
| 3.9 | Test clock renewal path (max 3 subs per clock, `proration_behavior=none`) | `backend/adapters/stripe_adapter.py` | Tylin | ⬜ | 2.1 | |
| 3.10 | HTTP MCP server + printed curl | `backend/mcp/server.py` | Khadim | ⬜ | 2.10 | |
| 3.11 | Arga twins spike, 30 minute cap, keep only if it writes | `backend/evals/` | Khadim | ⬜ | 3.1 | |
| 3.12 | Mutation-test the eval gates both directions | `backend/evals/` | Khadim | ⬜ | 3.1 | |
| 3.13 | `/verify`: browser recomputes JCS + SHA-256 chain, verifies Ed25519 signature, tamper toggle | `web/app/verify/` `web/lib/verify/` | Stephen | 🟡 | 3.4 | Built and live; 12 tests incl. golden vectors matching Python hashlib. Unverified against a real export until 3.4 exists |
| 3.14 | Proof + `/evals` board | `web/app/evals/` | Stephen | ⬜ | 3.5 | |
| 3.15 | `/break` judge panel streaming chapters live | `web/app/break/` | Stephen | ⬜ | 3.7 | |
| 3.16 | Live drift strip | `web/components/DriftStrip.tsx` | Stephen | ⬜ | 3.6 | |
| 3.17 | `/judges` itinerary with deep links and curl commands | `web/app/judges/` `web/components/JudgeTour.tsx` | Stephen | ✅ | 3.5 | Live; backend stops marked live only after a browser health check succeeds |
| 3.18 | Sound design + subtitles toggle (muted by default) | `web/components/Sound*.tsx` | Stephen | ⬜ | 1.14 | |
| 3.19 | Mobile pass, axe, Lighthouse | `web/` `web/tests/e2e/` | Stephen | 🟡 | 2.16 | 14:00 ET. axe WCAG 2.1 AA 6/6 on production (desktop + mobile); mobile stills reviewed; Lighthouse not run yet |
| 3.20 | Deployed smoke workflow against the live URL | `.github/workflows/deployed-smoke.yml` | Stephen | 🟡 | 2.11 | Page and asset checks green on `9b13a6e`; add `/api/health` and a run once the backend is deployed |

**CHECKPOINT 4:45 PM ET: midpoint rubric re-audit. Count what each criterion's surface shows today, fix the weakest.**

### Phase 4: Freeze and submit (5:45 to 7:00 PM ET)

Freeze policy from 5:45 ET: only claim corrections, guard additions, tests and docs. New stateful code waits.

| # | Component | File(s) | Owner | Status | Deps | Notes |
|---|---|---|---|---|---|---|
| 4.1 | Whole-repo fresh-eyes pass + second-model adversarial review | n/a | Stephen | ⬜ | Phase 3 | Seam between lanes first |
| 4.2 | Fact sheet generated from `/api/proof` + eval output | `docs/fact-sheet.md` | Stephen | ⬜ | 3.5 | Only number source for video, README, brief |
| 4.3 | Reliability brief + PDF | `docs/reliability-brief.md` `.pdf` | Stephen | ⬜ | 4.2 | Tylin reviews FMEA rows |
| 4.4 | Final README | `README.md` | Stephen | ⬜ | 4.2 | |
| 4.5 | Stills of every judge screen from the deployed origin, desktop + 390 px | local | Stephen | ⬜ | 3.19 | |
| 4.6 | Record and edit the 2:00 video; verify frames, duration, loudness | local | Stephen | ⬜ | 4.2 | |
| 4.7 | Sweeps: em-dash, AI tone, claims vs code, env vars vs code | repo | Stephen | ⬜ | 4.4 | |
| 4.8 | Full-history gitleaks scan on the final SHA (repo is already public) | repo | Stephen | ⬜ | 4.7 | |
| 4.9 | Clean-clone quickstart repro on a fresh directory | n/a | Tylin | ⬜ | 4.4 | |
| 4.10 | Warm DB + backend, confirm Slack socket connected, keep hosts up through judging | hosts | Tylin | ⬜ | 2.11 | |
| 4.11 | Submit, then verify the confirmation by reload | form | Stephen | ⬜ | 4.6 4.8 | By 6:50 ET |

---

## Team lanes and zero-collision file ownership

Nothing in these lists overlaps. If you need a change in the other lane, write it under Open Questions and ping. Do not edit.

**Tylin:** `backend/**` except Khadim's paths below · `shared/openapi.json` · `.github/workflows/backend.yml` · `Makefile` · `docker-compose.yml` · `TYLIN_TASKS.md`

**Khadim:** `backend/evals/**` · `backend/monitor/**` · `backend/mcp/**` · `backend/api/routes_sandbox.py` · `backend/api/routes_proof.py` · `backend/tests/evals/**` · `KHADIM_TASKS.md`

**Stephen:** `web/**` · `docs/**` except `docs/contracts/api.md` · `README.md` · `.github/workflows/web.yml` · `.github/workflows/deployed-smoke.yml` · `STEPHEN_TASKS.md` · `.gitignore` · `.env.example`

**Shared (PR + both approve):** `docs/contracts/api.md` · `PLAN.md` status rows (each person edits only their own rows) · `AGENTS.md`

---

## Shared Contracts

Full definitions: [docs/contracts/api.md](docs/contracts/api.md). Generated source of truth for types: `shared/openapi.json`.

| Contract | Owner | Consumers | Definition |
|---|---|---|---|
| `Money` | Tylin | Stephen | `{ minor_units: int, currency: lowercase ISO 4217 }`. No floats on the wire. |
| `Outcome` | Tylin | Stephen | `SUCCESS \| PARTIAL \| REFUSED \| NEEDS_HUMAN` |
| `RunSummary` | Tylin | Stephen | `GET /api/runs/{id}` |
| SSE `Envelope` + event types | Tylin | Stephen | `{ seq, run_id, type, at, payload }`, `Last-Event-ID` replay |
| Ledger chain rule | Tylin | Stephen (`/verify`) | `sha256(prev_hash_bytes \|\| RFC8785(payload))`, genesis 32 zero bytes, Ed25519 over head bytes |
| `Proof` | Khadim | Stephen | `GET /api/proof`, recomputed per request |
| Sandbox scenarios | Khadim | Stephen (`/break`) | `POST /api/sandbox/runs` enum |
| Eval scenario file format | Khadim | Tylin (harness hooks) | One file per scenario: seed, request, faults, expected outcome, expected end state in minor units |

---

## Decisions (locked)

- **D1** Full 20-scenario spec plus public demo surfaces (break-it panel, browser verification, drift detector, MCP). Dependency order guarantees a complete loop first.
- **D2** Web: Next.js 16 App Router, Tailwind 4, shadcn for console parts, GSAP for motion, Lottie for loaders, one light WebGL paper shader.
- **D3** Experience is "live run as chapters". Every animation beat fires on a real SSE event, never on a timer.
- **D4** Theme "ledger paper": paper, ink green, olive, bordeaux, marbled endpapers, rubber-stamp outcomes. Outcome colors stay semantic.
- **D5** Seam: FastAPI + SSE; Pydantic produces `shared/openapi.json`; web types are generated from it and CI fails on drift.
- **D6** Hosting: web on Vercel (`pricequorum-web`), backend on a long-running host, Postgres on Supabase.
- **D7** Backend accounts created and held by Tylin (shared with Khadim privately, never in git); Vercel and design assets by Stephen.
- **D8** Git: commit straight to `main` after `git pull --rebase`, one logical change per commit, push immediately. Contract changes go through a PR.
- **D9** Stripe test mode only. A live key is refused at startup. Test mode is Stripe's real API without money moving, not mock data.
- **D10** Repo is public from 13:05 ET. Team strategy notes live outside this repo. Every push is public the moment it lands, so secrets hygiene applies to every commit, not just the last one.

## Open Questions

- [ ] **Q1** Submission form URL and video host? Needs whoever attended the opening.
- [ ] **Q2** Model name for the planner (current GPT-5 class with strict structured outputs). Tylin.
- [ ] **Q3** Backend host: Railway or Render? Tylin.

## Risk Register

| Risk | Mitigation |
|---|---|
| Slack socket drops on camera | Pre-warm; operator fallback endpoint calls the same resume function; UI labels the mode |
| Airtable 429 waits 30 s on camera | Space writes; cache reads; demo against the seeded plan only |
| DB cold start | Hit `/api/health` right before recording and before judging |
| Float compare false divergence | `money.py` everywhere; any float `==` on amounts blocks the merge |
| Contract drift between lanes | Generated types + CI drift check + PR for contract edits |
| A green suite with dead runtime wiring | Attempt the gated action against the running system and watch it refuse |
| Demo shows something not live | Claims grep before submit; fixtures never shipped; `injected` faults labeled |

## Coordination Protocol

1. **Before starting a task:** set status to 🟡 with `HH:MM ET` in Notes, commit `PLAN.md` only, push. That is your lock.
2. **After finishing:** flip to ✅, commit `PLAN.md`, push.
3. **If blocked:** ⛔ plus a one-line note, ping the other person.
4. **Before starting ANY task:** `git pull --rebase` and re-read `PLAN.md`.
5. **Hotfixes:** commit the fix, update `PLAN.md` after. Process never blocks an emergency.
6. **`PLAN.md` commits are atomic.** Never bundle a status change with code.
7. **Commit messages:** status updates `status: [#] emoji description`. Code uses Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`), subject 100 characters or less. Contract changes `⚠️ CONTRACT: field, reason`.
8. **Handoffs:** `→ Name` in Notes.
9. **Stale locks:** TTL 1 hour, ping first, then claim.
10. **Contract changes are announced before they are committed.**
11. **Stage named paths only.** Never `git add -A` or `git add .`.
12. **No em-dashes anywhere** (code, comments, commits, docs, UI copy, video script). Use a period, colon, comma or parentheses.
13. **Never commit secrets.** `.env` is ignored; `.env.example` holds names only.
14. **Edit `PLAN.md` fresh.** Pull, then edit only your own rows. Never paste an older copy over the file.

## CI rules

- Every gate runs bare: no pipe on the exit path. `cmd | tail` hides failures.
- A skipped test under CI is a false green. Guards fail under `CI`, never skip.
- After each push, read the check-runs for that exact SHA: `gh api repos/StephenSook/pricequorum/commits/<SHA>/check-runs --jq '.check_runs[] | "\(.conclusion) \(.name)"'`. Never trust a `--watch` exit code.
- Mirror every command the CI job runs locally before committing.

## Cut list (only if the clock forces it, in this order)

1. Arga twins spike (3.11)
2. Sound design (3.18)
3. MCP server (3.10)
4. Test clock renewal (3.9)
5. WebGL shader (static paper image stays)

Never cut: read-back verifier, idempotency ledger, Slack gate, remedy-returning refusals, the eval number with a named failure.

## Definition of done

- A stranger opens the public URL with no keys, runs a request and a `/break` scenario, and watches real Stripe, Notion and Airtable change or refuse.
- `/api/proof` recomputes the headline number; `/verify` checks the chain in the browser.
- CI green for the submitted SHA, per job.
- Video, brief and README draw every number from `docs/fact-sheet.md`.

## Verification: prove it works end to end

1. Incognito browser on the public URL: happy path, timeout after commit, prompt injection, locked record, chain tamper.
2. Stripe, Notion and Airtable dashboards show the values the UI read back.
3. `uv run python backend/ledger/verify_ledger.py` and `/verify` both report the same head.
4. Fresh clone, `.env` filled, `make seed && make run && make verify` succeeds.
