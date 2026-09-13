# PriceQuorum backend

FastAPI service that changes one SaaS plan price exactly once across Stripe, Notion and Airtable, behind a Slack approval, and proves the result by reading every system back. The API contract is `docs/contracts/api.md`; the generated schema is `shared/openapi.json`.

## Layout

| Path | What it does |
|---|---|
| `pricequorum/ports.py` | The seam between the run loop and the vendor adapters |
| `pricequorum/adapters/` | Stripe, Notion, Airtable and Slack adapters, fault injection |
| `pricequorum/orchestrator.py` | The run loop: parse, resolve, policy, approval, writes, read-back, outcome |
| `pricequorum/policy.py` | Every rule that can refuse a change, in one file with no model import |
| `pricequorum/resolver.py` | Matches one plan across the three apps; low confidence goes to a person |
| `pricequorum/ledger.py` | Pending rows before each call, RFC 8785 hash chain, Ed25519 signed head |
| `pricequorum/verifier.py` | Fresh read-backs and the invariant register |
| `pricequorum/api/app.py` | HTTP routes, the event stream, operator approval, proof; mounts the MCP server at `/mcp/` |
| `pricequorum/sandbox.py` | The judge sandbox: seven scenarios against the `judge_pro` plan only |
| `pricequorum/monitor.py` | Drift monitor: Notion and Airtable against Stripe, polled only while someone listens |
| `mcp_server/` | Four MCP tools over Streamable HTTP that call this API |

## Run locally

```
uv sync
export DATABASE_URL=postgresql://postgres@localhost:5432/pricequorum
uv run uvicorn pricequorum.api.app:app --reload
```

Vendor credentials use the names in `../.env.example`. Without them the API starts and `/api/health` names each app that is not configured.

## Checks

```
uv run ruff format --check .
uv run ruff check .
uv run mypy pricequorum
uv run pytest -q
uv run python -m pricequorum.openapi --check
```

Tests need a Postgres reachable through `DATABASE_URL`. Test doubles live in `tests/fakes.py` and are never imported by the app.

## Deploy

`render.yaml` describes a free Render web service built from `Dockerfile` and a free Render Postgres. Slack Socket Mode and the approval sweeper run inside the web process.
