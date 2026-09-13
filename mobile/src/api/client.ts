/**
 * Thin client for the PriceQuorum backend, the same calls and error wording as
 * web/lib/api/client.ts. React Native has no AbortSignal.timeout, so deadlines use an
 * AbortController with a timer. Nothing the backend did not send is filled in.
 */
import { readHealth, type HealthCheck } from "../shared/api/health";

export type { HealthCheck };

const CREATE_RUN_TIMEOUT_MS = 20_000;
const READ_TIMEOUT_MS = 15_000;

export class ApiError extends Error {
  readonly status: number | null;
  readonly remedy: string | null;

  constructor(message: string, status: number | null, remedy: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.remedy = remedy;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

type Deadline = { signal: AbortSignal; expired: () => boolean; clear: () => void };

function deadline(timeoutMs: number): Deadline {
  const controller = new AbortController();
  let expired = false;
  const timer = setTimeout(() => {
    expired = true;
    controller.abort();
  }, timeoutMs);
  return { signal: controller.signal, expired: () => expired, clear: () => clearTimeout(timer) };
}

export type CreatedRun = { runId: string; eventsUrl: string | null };

export async function createRun(base: string, requestText: string): Promise<CreatedRun> {
  if (!base) {
    throw new ApiError("The app does not know where the backend runs.", null, "Add the backend address in Settings.");
  }
  const limit = deadline(CREATE_RUN_TIMEOUT_MS);
  try {
    let res: Response;
    try {
      res = await fetch(`${base}/api/runs`, {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify({ request_text: requestText }),
        signal: limit.signal,
      });
    } catch (err) {
      console.warn("[PriceQuorum] POST /api/runs failed", err);
      throw new ApiError(
        limit.expired()
          ? `The backend at ${base} did not answer within ${CREATE_RUN_TIMEOUT_MS / 1000} seconds.`
          : `The PriceQuorum backend at ${base} is not reachable.`,
        null,
        "Try again in a moment.",
      );
    }

    const body: unknown = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = isRecord(body) && typeof body.detail === "string" ? body.detail : null;
      const remedy = isRecord(body) && typeof body.remedy === "string" ? body.remedy : null;
      const retryAfter = isRecord(body) && typeof body.retry_after === "number" && body.retry_after >= 0 ? body.retry_after : null;
      throw new ApiError(
        detail ?? `The backend answered with status ${res.status}.`,
        res.status,
        remedy ?? (retryAfter !== null ? `Try again in ${retryAfter} seconds.` : null),
      );
    }
    if (!isRecord(body) || typeof body.run_id !== "string") {
      throw new ApiError("The backend accepted the request but did not return a run id.", res.status, null);
    }
    return { runId: body.run_id, eventsUrl: typeof body.events_url === "string" ? body.events_url : null };
  } finally {
    limit.clear();
  }
}

/** Never throws; the caller decides what each state means. */
export async function checkHealth(base: string, timeoutMs = 5000): Promise<HealthCheck> {
  if (!base) return { state: "unconfigured" };
  const limit = deadline(timeoutMs);
  try {
    let res: Response;
    try {
      res = await fetch(`${base}/api/health`, { headers: { accept: "application/json" }, signal: limit.signal });
    } catch (err) {
      console.warn("[PriceQuorum] GET /api/health failed", err);
      return { state: "unreachable", status: null };
    }
    if (!res.ok) return { state: "unreachable", status: res.status };
    return readHealth(await res.json().catch(() => null));
  } finally {
    limit.clear();
  }
}

export type JsonResult = { ok: true; body: unknown } | { ok: false; detail: string };

/** GET a JSON endpoint with a deadline that covers the body as well as the headers. */
export async function fetchJson(base: string, path: string, timeoutMs = READ_TIMEOUT_MS): Promise<JsonResult> {
  const limit = deadline(timeoutMs);
  try {
    let res: Response;
    try {
      res = await fetch(`${base}${path}`, { headers: { accept: "application/json" }, signal: limit.signal });
    } catch (err) {
      console.warn(`[PriceQuorum] ${path} could not be fetched`, err);
      return {
        ok: false,
        detail: limit.expired() ? `${path} did not answer within ${timeoutMs / 1000} seconds.` : `${path} at ${base} is not reachable.`,
      };
    }
    if (!res.ok) return { ok: false, detail: `${path} answered with status ${res.status}.` };
    try {
      return { ok: true, body: await res.json() };
    } catch {
      return {
        ok: false,
        detail: limit.expired() ? `${path} did not finish within ${timeoutMs / 1000} seconds.` : `${path} answered, but not with JSON.`,
      };
    }
  } finally {
    limit.clear();
  }
}
