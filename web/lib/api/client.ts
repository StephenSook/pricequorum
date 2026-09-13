/**
 * Thin client for the PriceQuorum backend.
 *
 * Response shapes are validated at runtime here until `shared/openapi.json` is published
 * by the backend. At that point these parsers switch to the generated types in
 * `lib/api/types.ts` (see docs/contracts/api.md). No response shape is invented here:
 * anything the backend did not send is reported as an error, never filled in.
 */

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");

const CREATE_RUN_TIMEOUT_MS = 20_000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly remedy: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readErrorBody(body: unknown): { detail: string | null; remedy: string | null; retryAfter: number | null } {
  if (!isRecord(body)) return { detail: null, remedy: null, retryAfter: null };
  return {
    detail: typeof body.detail === "string" ? body.detail : null,
    remedy: typeof body.remedy === "string" ? body.remedy : null,
    retryAfter: typeof body.retry_after === "number" && body.retry_after >= 0 ? body.retry_after : null,
  };
}

function requireBase(): string {
  if (!API_BASE) {
    throw new ApiError(
      "The web app does not know where the backend runs.",
      null,
      "Set NEXT_PUBLIC_API_BASE_URL and reload the page.",
    );
  }
  return API_BASE;
}

const isTimeout = (err: unknown) => err instanceof DOMException && err.name === "TimeoutError";

export type CreatedRun = { runId: string; eventsUrl: string | null };

export async function createRun(requestText: string): Promise<CreatedRun> {
  const base = requireBase();
  let res: Response;
  try {
    res = await fetch(`${base}/api/runs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ request_text: requestText }),
      signal: AbortSignal.timeout(CREATE_RUN_TIMEOUT_MS),
    });
  } catch (err) {
    console.warn("[PriceQuorum] POST /api/runs failed", err);
    throw new ApiError(
      isTimeout(err)
        ? `The backend at ${base} did not answer within ${CREATE_RUN_TIMEOUT_MS / 1000} seconds.`
        : `The PriceQuorum backend at ${base} is not reachable.`,
      null,
      "Try again in a moment.",
    );
  }

  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const { detail, remedy, retryAfter } = readErrorBody(body);
    throw new ApiError(
      detail ?? `The backend answered with status ${res.status}.`,
      res.status,
      remedy ?? (retryAfter !== null ? `Try again in ${retryAfter} seconds.` : null),
    );
  }
  if (!isRecord(body) || typeof body.run_id !== "string") {
    throw new ApiError("The backend accepted the request but did not return a run id.", res.status, null);
  }
  return {
    runId: body.run_id,
    eventsUrl: typeof body.events_url === "string" ? body.events_url : null,
  };
}

export type HealthCheck =
  | { state: "unconfigured" }
  | { state: "unreachable"; status: number | null }
  | { state: "degraded"; problems: string[] }
  | { state: "healthy" };

/**
 * Reads a `GET /api/health` body. A 200 alone proves nothing (a proxy fallback page is also a
 * 200), so the backend is healthy only when the body itself says every part is up.
 */
export function readHealth(body: unknown): HealthCheck {
  if (!isRecord(body)) return { state: "degraded", problems: ["the health response is not the expected JSON"] };
  const problems: string[] = [];
  if (body.ok !== true) problems.push("the backend reports it is not ok");
  if (body.db !== "ok") problems.push("database not ok");
  if (body.slack_socket !== "connected") problems.push("Slack approvals not connected");
  if (body.stripe_mode !== "test") problems.push("Stripe is not in test mode");
  return problems.length > 0 ? { state: "degraded", problems } : { state: "healthy" };
}

/** Best-effort warm-up call. Never throws; the caller decides what each state means. */
export async function checkHealth(timeoutMs: number): Promise<HealthCheck> {
  if (!API_BASE) return { state: "unconfigured" };
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(timeoutMs), cache: "no-store" });
  } catch (err) {
    console.warn("[PriceQuorum] GET /api/health failed", err);
    return { state: "unreachable", status: null };
  }
  if (!res.ok) return { state: "unreachable", status: res.status };
  return readHealth(await res.json().catch(() => null));
}
