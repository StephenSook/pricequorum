// GENERATED from web/lib/api/health.ts by mobile/scripts/sync-shared.mjs.
// Do not edit this copy. Change the web file, then run: npm run sync

/**
 * The health contract (`GET /api/health`), shared by the web app and the mobile app.
 *
 * A 200 alone proves nothing (a proxy fallback page is also a 200), so the backend is healthy
 * only when the body itself says every part is up.
 */

export type HealthCheck =
  | { state: "unconfigured" }
  | { state: "unreachable"; status: number | null }
  | { state: "degraded"; problems: string[] }
  | { state: "healthy" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function readHealth(body: unknown): HealthCheck {
  if (!isRecord(body)) return { state: "degraded", problems: ["the health response is not the expected JSON"] };
  const problems: string[] = [];
  if (body.ok !== true) problems.push("the backend reports it is not ok");
  if (body.db !== "ok") problems.push("database not ok");
  if (body.slack_socket !== "connected") problems.push("Slack approvals not connected");
  if (body.stripe_mode !== "test") problems.push("Stripe is not in test mode");
  return problems.length > 0 ? { state: "degraded", problems } : { state: "healthy" };
}
