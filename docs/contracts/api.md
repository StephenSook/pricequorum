# PriceQuorum API contract (v1)

Owner: Tylin (backend produces it). Consumer: Stephen (web). Co-owned document.

**Drift here is integration bugs.** Change a field only through a PR titled `⚠️ CONTRACT: <field>, <reason>`, approved by the other lane, merged together with the regenerated `shared/openapi.json`. The web CI regenerates `web/lib/api/types.ts` from `shared/openapi.json` and fails on any diff, so a backend rename breaks the web build instead of the demo.

## Global rules

1. **Money never crosses the wire as a float.** Every amount is `Money = { "minor_units": int, "currency": string }`, currency lowercase ISO 4217 (`"usd"`). Raw values read from Notion or Airtable appear only in `raw_value` fields, as strings, for display.
2. **Hashes and signatures are lowercase hex strings** in JSON (64 chars for SHA-256, 128 for Ed25519 signatures, 64 for public keys). The database may store bytea.
3. **Timestamps** are ISO 8601 UTC strings.
4. **Errors** use `{ "error": string, "detail": string, "remedy": string | null }` with a meaningful HTTP status.
5. **Enums**
   - `Outcome`: `"SUCCESS" | "PARTIAL" | "REFUSED" | "NEEDS_HUMAN"`
   - `AppName`: `"stripe" | "notion" | "airtable" | "slack"`
   - `RunStatus`: `"running" | "awaiting_human" | "done" | "refused" | "failed"`
   - `LedgerState`: `"pending" | "completed" | "failed" | "compensated"`
   - `ApprovalDecision`: `"PENDING" | "APPROVED" | "DENIED" | "EXPIRED"`
6. **CORS** allows the origins in `PQ_ALLOWED_ORIGINS`. The SSE responses must carry `access-control-allow-origin` too (verified by a test that fetches with an `Origin` header).
7. **Nothing shown in the UI as live may come from a fixture.** Web fixtures are typed from the generated types, used only in dev and unit tests, and never shipped.

## REST endpoints

### `GET /api/health`
`{ ok: bool, version: string, commit_sha: string, db: "ok" | "down", stripe_mode: "test", slack_socket: "connected" | "down" }`

### `POST /api/runs`
Body: `{ request_text: string (1..500), change_key?: string }`
- `202` `{ run_id: uuid, events_url: string }`
- `409` `{ error: "run_in_progress", detail, remedy, active_run_id }`
- `422` validation, `429` rate limited with `retry_after` seconds.

### `GET /api/runs/{run_id}` returns `RunSummary`
```json
{
  "run_id": "uuid",
  "request_text": "raise Pro to $25/month",
  "status": "done",
  "outcome": "SUCCESS",
  "remedy": null,
  "created_at": "2026-09-13T20:01:02Z",
  "plan_key": "pro",
  "new_amount": { "minor_units": 2500, "currency": "usd" },
  "resolution": {
    "plan_key": "pro",
    "stripe_product_id": "prod_...",
    "stripe_price_id_old": "price_...",
    "stripe_price_id_new": "price_...",
    "notion_page_id": "uuid",
    "airtable_record_id": "rec...",
    "confidence": 100,
    "decided_by": "exact_id"
  },
  "approval": {
    "decision": "APPROVED",
    "mode": "slack",
    "approver_display": "Stephen",
    "decided_at": "...",
    "expires_at": "...",
    "slack_channel": "C...",
    "slack_ts": "...",
    "args_hash": "hex"
  },
  "readback": [ ReadbackResult ],
  "invariants": [ InvariantResult ],
  "ledger": [ LedgerRow ],
  "chain_head": "hex",
  "signature": "hex",
  "public_key": "hex"
}
```
`resolution`, `approval`, `chain_head`, `signature` may be `null` while a run is in progress. `approval.mode` is `"slack" | "operator" | "sandbox_auto"` and the UI must label the non-Slack modes.

`ReadbackResult`: `{ app: AppName, value: Money | null, raw_value: string | null, fresh: true, read_at, source_id: string }`

`InvariantResult`: `{ name: string, ok: bool, detail: string, outcome: Outcome }`

`LedgerRow`: `{ id: int, run_id, step_no: int, app: AppName, action: string, idempotency_key: string, args_hash: hex, state: LedgerState, external_object_id: string | null, outcome: Outcome | null, remedy: string | null, prev_hash: hex, entry_hash: hex, created_at, completed_at | null }`

### `GET /api/runs/{run_id}/events` (Server-Sent Events)
Each message:
```
id: <seq>
event: <type>
data: <Envelope JSON>

```
- `Envelope = { seq: int, run_id: uuid, type: EventType, at: ISO8601, payload: object }`
- Supports `Last-Event-ID` replay from the database, so a reconnect never loses a chapter.
- Heartbeat comment `: ping` every 15 seconds.
- The stream ends after `run.outcome`.
- Events are persisted before they are sent. The same sequence can be fetched with `GET /api/runs/{run_id}/events.json` (plain JSON array) for replays and the video.

### `POST /api/runs/{run_id}/approval`
Header `X-Operator-Token`. Body `{ decision: "approve" | "deny" }`. Calls the same resume function as the Slack button. `200 { decision }`, `409` if already decided (single-winner transition).

### `GET /api/ledger/export`
Whole chain, in id order (hackathon-sized ledger).
```json
{
  "algorithm": { "hash": "sha256", "canonicalization": "RFC8785", "signature": "ed25519" },
  "genesis": "0000000000000000000000000000000000000000000000000000000000000000",
  "rows": [ { "id": 1, "run_id": "uuid", "prev_hash": "hex", "entry_hash": "hex", "payload": { } } ],
  "head": "hex",
  "signature": "hex",
  "public_key": "hex"
}
```
**Chain rule:** `entry_hash = sha256(bytes(prev_hash) || RFC8785(payload))`, starting from 32 zero bytes. `payload` is returned exactly as hashed and must contain no floats. `signature = ed25519_sign(bytes(head))`. The browser verifier in `/verify` reimplements this rule, so any change here is a contract change.

### `POST /api/ledger/verify`
`{ ok: bool, entries: int, head: hex, signature_valid: bool, first_bad_id: int | null, expected: hex | null, got: hex | null }`

### `GET /api/public-key`
`{ public_key: hex, algorithm: "ed25519" }`

### `GET /api/proof` (unauthenticated, recomputed on every request)
```json
{
  "generated_at": "...",
  "commit_sha": "...",
  "scenarios": { "passed": 19, "total": 20, "wilson_95": [0.76, 0.99], "runs_per_scenario": 3 },
  "outcomes": { "SUCCESS": 0, "PARTIAL": 0, "REFUSED": 0, "NEEDS_HUMAN": 0 },
  "duplicate_writes_prevented": 0,
  "forbidden_actions_refused": { "refused": 0, "attempted": 0 },
  "named_failures": [ { "scenario_id": "string", "explanation": "string" } ],
  "ledger": { "entries": 0, "chain_intact": true, "signature_valid": true },
  "live_runs": { "total": 0, "success": 0 },
  "last_eval_run_at": "..."
}
```
The numbers above are shape examples only. Real values come from the database.

### `GET /api/evals/latest`
`{ run_at, commit_sha, summary: <same as proof.scenarios>, results: [ { scenario_id, description, expected_outcome: Outcome, observed_outcome: Outcome | null, passed: bool, run_id: uuid | null, detail: string } ] }`

### `GET /api/monitor/events` (SSE)
Event types: `monitor.ok { checked_at }`, `drift.detected { plan_key, app, expected: Money, observed: Money | null, raw_value, detected_at }`, `drift.healed { plan_key, app, run_id }`.

### `POST /api/monitor/heal`
Body `{ plan_key }`. Starts a run that writes derived surfaces only. `202 { run_id, events_url }`.

### `POST /api/sandbox/runs` (judge "Break it" panel, unauthenticated, rate limited)
Body `{ scenario: "happy_path" | "timeout_after_commit" | "prompt_injection" | "locked_record" | "chain_tamper" | "concurrent_runs" | "drift" }`
- `202 { run_ids: uuid[], events_urls: string[], sandbox_plan_key: string, approval_mode: "slack" | "sandbox_auto" }`
- `429 { error: "rate_limited", retry_after: int }`
- Runs against an isolated judge plan in Stripe test mode, Notion and Airtable, reset by a job. `chain_tamper` operates on a sandbox copy of the chain, never the real ledger.

### `GET /api/sandbox/status`
`{ available: bool, queue_depth: int, cooldown_seconds: int }`

### `POST /mcp`
Streamable HTTP MCP server. Tools: `run_price_change`, `get_run`, `verify_chain`, `get_proof`. The README prints a working `curl`.

## SSE event types (payloads)

Normal order: `run.created`, `intent.parsed`, `resolve.completed`, `policy.decided`, `approval.requested`, `approval.decided`, then per write step `ledger.pending`, optional `adapter.fault` and `readback.recovery`, `ledger.completed`, then `readback.result` x3, `invariant.result` xN, `run.outcome`. A refusal or NEEDS_HUMAN jumps straight to `run.outcome` after the deciding event.

| type | payload |
|---|---|
| `run.created` | `{ request_text }` |
| `run.status` | `{ status: RunStatus }` |
| `intent.parsed` | `{ plan_hint: string, new_amount: Money, interval: "month" \| "year" }` |
| `resolve.completed` | `{ plan_key, stripe_product_id, stripe_price_id, notion_page_id, airtable_record_id, confidence: number, decided_by: "exact_id" \| "fuzzy" \| "human", candidates: [ { app, label, score } ] }` |
| `policy.decided` | `{ decision: "ALLOW" \| "REFUSED" \| "NEEDS_HUMAN", rule: string, detail: string, remedy: string \| null }` |
| `approval.requested` | `{ summary: string, args_hash, slack_channel, slack_ts, expires_at, mode }` |
| `approval.decided` | `{ decision: ApprovalDecision, approver_display: string \| null, decided_at, mode }` |
| `ledger.pending` | `{ ledger_id: int, step_no, app, action, idempotency_key, args_hash }` |
| `adapter.fault` | `{ ledger_id, call_site: string, kind: "timeout" \| "rate_limit" \| "conflict_409" \| "server_5xx", injected: bool }` |
| `readback.recovery` | `{ ledger_id, call_site, found_landed: bool, external_object_id: string \| null }` |
| `ledger.completed` | `{ ledger_id, step_no, external_object_id, prev_hash, entry_hash }` |
| `subscription.migrated` | `{ subscription_id, from_price, to_price, proration_behavior }` |
| `renewal.invoice` | `{ invoice_id, amount: Money, test_clock_id }` |
| `readback.result` | `ReadbackResult` |
| `invariant.result` | `InvariantResult` |
| `run.outcome` | `{ outcome: Outcome, remedy: string \| null, chain_head, signature, public_key }` |

`adapter.fault.injected` is true whenever the fault came from `PQ_FAULT`, and the UI must say so. Honesty beats a scarier banner.
