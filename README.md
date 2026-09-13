# PriceQuorum

An agent that changes a SaaS plan's published price once, correctly, across Stripe, Notion, and Airtable, gated by a human approval in Slack, and proves it by reading every system back.

**Live:** https://pricequorum-web.vercel.app

**Status (Multi-App AI Agent Hackathon, September 13, 2026):** the web app is deployed and checked on every push. The backend is still being built. Until it is deployed, starting a run shows that the backend is not configured, and every page that needs backend data says so instead of showing placeholder numbers.

## How it works

| App | Role |
|---|---|
| Stripe | Authoritative billing. Prices are immutable, so a change is a migration: new Price, transfer lookup key, move default, archive old. |
| Notion | Derived public pricing page. Follows Stripe, never the other way. |
| Airtable | Derived SKU catalogue. Follows Stripe, never the other way. |
| Slack | Human approval gate before any consequential write. |

A run is reported as SUCCESS only after a fresh read of all three apps agrees. Every write is recorded in a hash-chained ledger whose head is signed with Ed25519.

## Pages

| Route | What it does | Needs the backend |
|---|---|---|
| `/` | Type a price change and follow the run as it happens | Yes, to start a run |
| `/runs/[id]` | The receipt for one run, rebuilt from its recorded events | Yes |
| `/verify` | Recomputes the ledger hash chain and checks the head signature in your browser | Yes, for the ledger export |
| `/evals` | Scenario pass rate, refusals, duplicate writes prevented, named failures | Yes |
| `/judges` | A short tour that marks each stop live only after the backend answers | No |

## How the web app is checked

- `.github/workflows/web.yml` runs on every push to `web/`: contract drift check, typecheck, lint, unit tests, production build.
- `.github/workflows/deployed-smoke.yml` checks the live site on every push to `web/` and every 30 minutes. On a push it waits for the live build to contain that commit, so a stale deployment fails. It then loads every route in a real browser on desktop and phone (`web/tests/e2e/`), failing on an uncaught error, a hydration failure, or a serious or critical axe (WCAG 2.1 A and AA) violation.
- The browser ledger verifier is tested against hashes computed independently with Python's `hashlib`.

## Run the web app locally

```
cd web
npm ci
npm run dev
```

Set `NEXT_PUBLIC_API_BASE_URL` to the backend address (see `.env.example`). Checks:

```
npm run typecheck
npm run lint
npm run test
npm run build
BASE_URL=http://localhost:3000 npm run e2e
```

## Repository

- `web/`: Next.js app (App Router, Tailwind 4, GSAP)
- `backend/`: FastAPI service (being built, not in the repository yet)
- `docs/contracts/api.md`: the API and event-stream contract between the two
- `PLAN.md`: task status and ownership

License: MIT.
