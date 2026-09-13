# Tylin Tasks

Personal task view. Source of truth is PLAN.md (task numbers match). Legend: [ ] not started · [-] in progress · [x] done · [!] blocked

Deadline: **7:00 PM ET submission.** Keep the backend host up and warm until 8:00 PM ET (judging runs 7:00 to 7:40 ET).

---

## Credentials to gather first (Phase 0)

Nothing below is committed. Values go in a local `.env` (gitignored), on the backend host, and as GitHub Actions secrets for the eval job. Names match `.env.example`.

| Name | Where you get it | Unblocks |
|---|---|---|
| `STRIPE_SECRET_KEY` | Stripe dashboard, **test mode** (or a sandbox), Developers, API keys. Must start with `sk_test_`. | 1.7 seed, 2.1 adapter, 3.1 evals, 3.9 test clock |
| `NOTION_TOKEN`, `NOTION_DATA_SOURCE_ID` | notion.so/profile/integrations, internal integration. Create the pricing database, then **share it with the integration** or every call returns `object_not_found`. Data source id comes from the database (API version `2025-09-03`). | 2.3 |
| `AIRTABLE_PAT`, `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE` | airtable.com/create/tokens with `data.records:read`, `data.records:write`, `schema.bases:read`, scoped to the base. | 2.4 |
| `SLACK_BOT_TOKEN` (`xoxb-`), `SLACK_APP_TOKEN` (`xapp-`), `SLACK_APPROVAL_CHANNEL` | api.slack.com/apps: create app, enable Socket Mode (app-level token with `connections:write`), Interactivity on, bot scopes `chat:write`, `channels:read`. Invite the bot to the channel. | 2.8 |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | platform.openai.com | 2.7 |
| `DATABASE_URL` | Supabase project, connection string (use the pooler URL on the host) | 1.2 onward |
| `PQ_SIGNING_KEY` | Generate once: `uv run python -c "from nacl.signing import SigningKey; print(SigningKey.generate().encode().hex())"` | 3.3 |
| `PQ_OPERATOR_TOKEN` | Any long random string | 2.8 fallback endpoint |

**Invite Stephen** as a viewer to the Notion page, the Airtable base and the Slack channel. He films those screens.

---

## Lane ownership (edit only these)

- `backend/**`
- `shared/openapi.json`
- `.github/workflows/backend.yml`
- `Makefile`
- `docker-compose.yml`
- `TYLIN_TASKS.md`

Need something in `web/**` or `docs/**`? Put it under Open Questions in PLAN.md and ping Stephen.

---

## Phase 0: Setup (until 1:15 PM ET)

- [ ] **0.2** Stripe test key. Refuse `sk_live_` at process start.
- [ ] **0.3** Notion pricing data source: `Name` (title), `pq_plan_id` (text), `Price` (number, not rich text, not formula), `Currency` (select), `Locked` (checkbox). Shared with the integration.
- [ ] **0.4** Airtable SKU table: `pq_plan_id` (unique text, the merge key), `Price` (number), `Currency`, `Locked` (checkbox). PAT.
- [ ] **0.5** Slack app in Socket Mode, channel created, bot invited.
- [ ] **0.6** Supabase `DATABASE_URL`; `docker-compose.yml` with Postgres 16 as the offline fallback.
- [ ] **0.7** OpenAI key. **Open the Agents SDK Python human-in-the-loop guide and confirm the RunState serialize and restore method names before writing the adapter.** The JS names are verified, Python names are not.
- [ ] **0.8** Backend host project (long-running process, Socket Mode needs it).

## Phase 1: Foundations (until 2:30 PM ET)

- [ ] **1.1** `backend/` with uv, Python 3.12, FastAPI, `/api/health` shape from the contract, CORS from `PQ_ALLOWED_ORIGINS`.
- [ ] **1.2** Migrations from spec section 8, plus a `run_events` table (seq, run_id, type, payload jsonb, at).
- [ ] **1.3** Pydantic models for every shape in `docs/contracts/api.md`; `make openapi` writes `shared/openapi.json`. **Commit it by 1:45 ET and tell Stephen.** The SSE events should be one discriminated union on `type`.
- [ ] **1.4** `money.py` (spec section 4). `Decimal(str(x))`, never `Decimal(float)`. Tests for 25.00 stored as 24.999999999999996, JPY, KWD.
- [ ] **1.5** Ledger: `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING` before every external call; chain with `rfc8785` 0.1.4; `verify_ledger.py` prints `OK: N entries, chain intact, head=..., signature valid` or `TAMPER DETECTED at id=...`.
- [ ] **1.6** SSE: write the event row, then send. Honor `Last-Event-ID`. Heartbeat every 15 s. Add the CORS header on the stream response and a test that fetches it with an `Origin` header.
- [ ] **1.7** `make seed` and `make reset`: Pro plan at 2000 usd monthly with lookup key `standard_monthly` and metadata `pq_plan_id=pro`; Pro Plus; Pro EUR; matching Notion and Airtable rows. Reset archives prior prices (products with prices cannot be deleted).
- [ ] **1.8** `backend.yml`: `uv sync`, `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy .`, `uv run pytest -q`, `uv run pip-licenses --fail-on 'GPL;AGPL'`, gitleaks. Each step is its own line with no pipe.

## Phase 2: Full loop (until 3:45 PM ET)

- [ ] **2.1** Stripe migration exactly as spec section 5: create price with `lookup_key` + `transfer_lookup_key=true`; set product `default_price`; archive old with `active=false`. Idempotency keys `pq:{plan}:{version}:{step}`. Read back with `GET /v1/prices/{id}` and the product.
- [ ] **2.2** `faults.py`: raise AFTER the real request dispatches (`timeout_after_commit` on `stripe.price.create`, `rate_limit` on `airtable.upsert`). Every fault event carries `injected: true`.
- [ ] **2.3** Notion: `POST /v1/data_sources/{id}/query`, `PATCH /v1/pages/{page_id}` with `{"properties":{"Price":{"number":25}}}`, header `Notion-Version: 2025-09-03`. Locate by stored page id, never by title. Read `Locked` before writing.
- [ ] **2.4** Airtable: `PATCH` with `performUpsert.fieldsToMergeOn=["pq_plan_id"]`, max 10 records, write JSON numbers not strings, on 429 wait 30 s with jitter. Read back by record id. Read `Locked` before writing.
- [ ] **2.5** Resolver: exact `pq_plan_id` scores 100; otherwise normalize and `rapidfuzz.fuzz.token_sort_ratio`; accept at 90 or above, else NEEDS_HUMAN with remedy "add a matching pq_plan_id to the Stripe product, Notion page and Airtable record". Negative cases: Pro USD vs Pro EUR, Pro vs Pro (2023). 20 to 40 labeled rows, report P/R/F1 offline only.
- [ ] **2.6** `policy.py` from spec section 13, pure functions, constants at the top, no LLM import. One unit test per rule.
- [ ] **2.7** Agent: the model parses intent and proposes; code decides. Strict structured outputs. Datamark every string read from Notion, Airtable, Stripe metadata or Slack. The approval interrupt sits BEFORE the write tool, never after.
- [ ] **2.8** Slack: `ack()` first, resume async. `UPDATE paused_runs SET status='APPROVED' WHERE run_id=%s AND status='PENDING'`; zero rows means already decided. Sweeper expires after 30 minutes and updates the message. Approval record stores approver, decision, timestamp, plan, old and new price ids, args hash, ledger entry hash, channel, ts. The approval arrives from Slack or the operator token, never as a tool argument the model can fill.
- [ ] **2.9** Verifier: fresh GETs, convert to minor units, compare integers only. Invariant register from spec section 11. Overall verdict is the worst class.
- [ ] **2.10** Orchestrator emits the contract events in order, including `readback.recovery` when a fault fires.
- [ ] **2.11** Deploy. Send Stephen the base URL.

## Phase 3: Depth and judge-facing wow (until 5:45 PM ET)

- [ ] **3.1** Eval harness with all 20 scenarios from spec section 14. Report passed/total, per-outcome counts, runs per scenario, Wilson 95% interval, duplicate writes prevented, forbidden actions refused, named failures with explanations. Write rows to `eval_results`. `--ci` mode for Actions.
- [ ] **3.2** `pg_try_advisory_xact_lock(hashtext('plan:'||plan||':'||currency))` + partial unique index on active runs. Loser returns the winner's result or a clean REFUSED.
- [ ] **3.3** Ed25519 head signature with PyNaCl, `/api/public-key`.
- [ ] **3.4** `/api/ledger/export` and `/api/ledger/verify`. Payloads must contain no floats (JCS number rules).
- [ ] **3.5** `/api/proof` recomputed from the database on each request.
- [ ] **3.6** Drift monitor: poll derived surfaces every 10 s, emit `drift.detected`; heal writes Notion and Airtable only, never Stripe.
- [ ] **3.7** Judge sandbox: isolated judge plan, rate limit, reset job; `chain_tamper` edits a sandbox copy of the chain only.
- [ ] **3.8** Crash recovery: on startup, pending rows with no external id are resolved by reading back, then completed or retried with the same key.
- [ ] **3.9** Test clock: one clock, up to three customers and subscriptions, migrate with `proration_behavior=none`, advance one interval, emit `renewal.invoice`.
- [ ] **3.10** HTTP MCP server with tools `run_price_change`, `get_run`, `verify_chain`, `get_proof`, plus one working `curl` for the README.
- [ ] **3.11** Arga twins spike (30 minute cap). Keep only if a write lands.
- [ ] **3.12** Break each eval gate on purpose (for example flip an expected outcome) and confirm the suite goes red, then restore.

## Phase 4: Freeze

- [ ] **4.9** Fresh clone, fill `.env`, run the quickstart exactly as the README prints it.
- [ ] **4.10** Before judging: hit `/api/health`, confirm `slack_socket: connected`, run one live request.

---

## Contracts you own

Everything in `docs/contracts/api.md`, generated as `shared/openapi.json`. Change a field only through a PR titled `⚠️ CONTRACT: field, reason`, and regenerate `shared/openapi.json` in the same PR.

## Stripe details a former Stripe engineer will check

| Wrong | Right |
|---|---|
| PATCH `unit_amount` | Not accepted on update; create new price and archive old |
| `transfer_lookup` | `transfer_lookup_key` |
| `Idempotency_Key` | `Idempotency-Key` |
| Keys last 30 days | 24 hours (v1) |
| Concurrent same key returns 429 | Returns 409; 429 is rate limiting and is safe to retry with the same key |
| Archiving migrates subscriptions | Existing subscriptions "remain active until they're canceled" |
| "42 subscriptions on a test clock" | A clock holds three |

## Hard rules

1. No em-dashes anywhere: code, comments, commits, docs, strings.
2. Stage named paths only. Never `git add -A`.
3. CI gates run bare. No pipe on the exit path. A skipped test is a false green.
4. Commit format `type(scope): description`, one logical change per commit, push right away. Status updates `status: [#] emoji description`, never bundled with code.
5. Never compare money as floats.
6. SUCCESS only after a fresh read of every system confirms it.
7. Every refusal returns a remedy. Tools refuse with a structured result, they never throw at the agent.
8. Never claim a feature works until you have watched it work against the running system.
