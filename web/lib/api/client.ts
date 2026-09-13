/**
 * Thin client for the PriceQuorum backend.
 *
 * Response shapes are validated at runtime here until `shared/openapi.json` is published
 * by the backend. At that point these parsers switch to the generated types in
 * `lib/api/types.ts` (see docs/contracts/api.md). No response shape is invented here:
 * anything the backend did not send is reported as an error, never filled in.
 */

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");

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

function readErrorBody(body: unknown): { detail: string | null; remedy: string | null } {
  if (!isRecord(body)) return { detail: null, remedy: null };
  return {
    detail: typeof body.detail === "string" ? body.detail : null,
    remedy: typeof body.remedy === "string" ? body.remedy : null,
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

export type CreatedRun = { runId: string; eventsUrl: string | null };

export async function createRun(requestText: string): Promise<CreatedRun> {
  const base = requireBase();
  let res: Response;
  try {
    res = await fetch(`${base}/api/runs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ request_text: requestText }),
    });
  } catch {
    throw new ApiError(`The PriceQuorum backend at ${base} is not reachable.`, null, "Try again in a moment.");
  }

  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const { detail, remedy } = readErrorBody(body);
    throw new ApiError(detail ?? `The backend answered with status ${res.status}.`, res.status, remedy);
  }
  if (!isRecord(body) || typeof body.run_id !== "string") {
    throw new ApiError("The backend accepted the request but did not return a run id.", res.status, null);
  }
  return {
    runId: body.run_id,
    eventsUrl: typeof body.events_url === "string" ? body.events_url : null,
  };
}

export type HealthCheck = { reachable: boolean; status: number | null };

/** Best-effort warm-up call. Never throws; the caller decides what an unreachable backend means. */
export async function checkHealth(timeoutMs: number): Promise<HealthCheck> {
  if (!API_BASE) return { reachable: false, status: null };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}/api/health`, { signal: controller.signal, cache: "no-store" });
    return { reachable: res.ok, status: res.status };
  } catch {
    return { reachable: false, status: null };
  } finally {
    clearTimeout(timer);
  }
}
