# PriceQuorum

An agent that changes a SaaS plan's published price once, correctly, across Stripe, Notion, and Airtable, gated by a human approval in Slack, and proves it by reading every system back.

**Status:** building (Multi-App AI Agent Hackathon, September 13, 2026). This README is a stub and will be replaced with the quickstart, the live URL, the published ledger public key, and the evaluation results.

| App | Role |
|---|---|
| Stripe | Authoritative billing. Prices are immutable, so a change is a migration: new Price, transfer lookup key, move default, archive old. |
| Notion | Derived public pricing page. Follows Stripe, never the other way. |
| Airtable | Derived SKU catalogue. Follows Stripe, never the other way. |
| Slack | Human approval gate before any consequential write. |

Team coordination lives in [PLAN.md](PLAN.md). The API contract lives in [docs/contracts/api.md](docs/contracts/api.md).

License: MIT.
