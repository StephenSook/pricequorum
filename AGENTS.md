# AGENTS.md

Guidance for anyone (human or coding agent) working in this repository.

## What this is

PriceQuorum changes a SaaS plan's price exactly once across Stripe (authoritative), Notion and Airtable (derived), behind a Slack approval, and emits SUCCESS only after reading every system back.

## Layout

| Path | Owner | Stack |
|---|---|---|
| `backend/` | Tylin | Python 3.12, uv, FastAPI, OpenAI Agents SDK, Postgres |
| `web/` | Stephen | Next.js 16 App Router, Tailwind 4, GSAP |
| `shared/openapi.json` | Tylin (generated) | The API contract as data |
| `docs/contracts/api.md` | Both | The API contract as prose |

Coordination and task status: `PLAN.md`. Do not edit files outside your lane; open a question in `PLAN.md` instead.

## Commands

```
# backend
cd backend
uv sync
uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run pytest -q
uv run python evals/run_evals.py

# web
cd web
npm ci
npm run typecheck
npm run lint
npm run test
npm run build
```

Run every command the CI job runs before committing.

## Invariants that must never break

1. Money is `(minor_units: int, currency: str)`. No float comparison of amounts anywhere.
2. A Stripe Price amount is never edited. A change is: create price with `transfer_lookup_key`, set `default_price`, archive the old price.
3. Prices flow Stripe to Notion and Stripe to Airtable. Never the reverse.
4. A ledger row is written `pending` before every external call.
5. SUCCESS is emitted only after fresh reads of all three systems agree.
6. Refusals always carry a remedy. Agent-facing tools return structured refusals and never throw.
7. Human approval arrives from Slack or the operator endpoint, never as an argument the model supplies.
8. Stripe runs in test mode only.

## Commits

- One logical change per commit, Conventional Commits, subject 100 characters or less, pushed immediately.
- Stage named paths only.
- Contract changes: PR titled `⚠️ CONTRACT: field, reason` with regenerated `shared/openapi.json`.
- No em-dashes in code, comments, docs, commit messages or UI copy.
- Never commit `.env` or any credential.

## CI

- Gates run bare, no pipes on the exit path.
- A skipped guard under CI counts as a failure.
- Verify the check-runs for the pushed SHA, not the exit code of a watch command.
