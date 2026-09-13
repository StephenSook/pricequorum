# Fact sheet

The single source for every number and claim in the video, README and reliability brief. Nothing enters those artifacts unless it is on this page with its source.

Tags: **MEASURED** (produced by a command or endpoint, with the commit SHA) · **SOURCED** (quoted from a named external document) · **NOT YET MEASURED** (must not appear in any artifact).

## Product numbers

| Claim | Value | Tag | Source (command or endpoint, SHA) |
|---|---|---|---|
| Eval scenarios passed / total | pending | NOT YET MEASURED | `GET /api/proof` |
| Wilson 95% interval | pending | NOT YET MEASURED | `GET /api/proof` |
| Runs per scenario | pending | NOT YET MEASURED | `GET /api/evals/latest` |
| Duplicate writes prevented across forced retries | pending | NOT YET MEASURED | `GET /api/proof` |
| Forbidden actions refused / attempted | pending | NOT YET MEASURED | `GET /api/proof` |
| Named failures | pending | NOT YET MEASURED | `GET /api/evals/latest` |
| Ledger entries, chain intact, signature valid | pending | NOT YET MEASURED | `POST /api/ledger/verify` |
| Resolver precision / recall / F1 (offline, hand-labeled) | pending | NOT YET MEASURED | `backend/evals/labeled_plans.csv` run |

## External facts

| Claim | Tag | Source |
|---|---|---|
| Nearly four in five SaaS companies change pricing at least once a year, most several times | SOURCED | OpenView survey of 2,200 SaaS companies |
| 94% of B2B SaaS pricing leaders update pricing and packaging at least once a year | SOURCED | Paddle 2023 State of SaaS Pricing |
| Stripe: "After you create a price, you can only update its metadata, nickname, and active fields." | SOURCED | docs.stripe.com/products-prices/manage-prices |
| Stripe idempotency keys expire after 24 hours (v1) | SOURCED | Stripe API docs, idempotent requests |
| OWASP LLM06:2025 recommends human-in-the-loop approval for high-impact actions | SOURCED | OWASP Top 10 for LLM Applications 2025 |
| Pending-before-call pattern | SOURCED | Brandur Leach, brandur.org/idempotency-keys |
