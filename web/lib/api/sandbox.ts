/**
 * Client and parsers for the judge sandbox (docs/contracts/api.md: POST /api/sandbox/runs and
 * GET /api/sandbox/status). Every response is validated before the page uses it; a shape the
 * contract does not allow is reported as invalid, never filled in.
 */
import { API_BASE } from "@/lib/api/client";

export const SANDBOX_SCENARIOS = [
  "happy_path",
  "timeout_after_commit",
  "prompt_injection",
  "locked_record",
  "chain_tamper",
  "concurrent_runs",
  "drift",
] as const;
export type SandboxScenario = (typeof SANDBOX_SCENARIOS)[number];

export type ApprovalMode = "slack" | "sandbox_auto";

export type SandboxRuns = { runIds: string[]; eventsUrls: string[]; sandboxPlanKey: string; approvalMode: ApprovalMode };
export type SandboxStatus = { available: boolean; queueDepth: number; cooldownSeconds: number };

export type SandboxStart =
  | { kind: "unconfigured" }
  | { kind: "started"; runs: SandboxRuns }
  | { kind: "rate_limited"; retryAfter: number | null }
  | { kind: "unavailable"; status: number | null; detail: string }
  | { kind: "invalid"; reasons: string[] };

export type SandboxAvailability =
  | { kind: "unconfigured" }
  | { kind: "ready"; status: SandboxStatus }
  | { kind: "unavailable"; status: number | null }
  | { kind: "invalid"; reasons: string[] };

type Parsed<T> = { ok: true; value: T } | { ok: false; reasons: string[] };

const START_TIMEOUT_MS = 20_000;
const STATUS_TIMEOUT_MS = 8_000;
const RUN_ID = /^[A-Za-z0-9-]{8,64}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const count = (value: unknown): number | null => (Number.isInteger(value) && (value as number) >= 0 ? (value as number) : null);

export function parseSandboxRuns(body: unknown, scenario: SandboxScenario): Parsed<SandboxRuns> {
  if (!isRecord(body)) return { ok: false, reasons: ["The sandbox response is not a JSON object."] };
  const reasons: string[] = [];

  const runIds =
    Array.isArray(body.run_ids) && body.run_ids.every((id) => typeof id === "string" && RUN_ID.test(id)) ? (body.run_ids as string[]) : null;
  if (!runIds || runIds.length === 0) reasons.push("run_ids must be a non-empty list of run ids.");
  else if (new Set(runIds).size !== runIds.length) reasons.push("run_ids must not repeat a run.");

  const eventsUrls =
    Array.isArray(body.events_urls) && body.events_urls.every((url) => typeof url === "string" && url.trim() !== "")
      ? (body.events_urls as string[])
      : null;
  if (!eventsUrls) reasons.push("events_urls must be a list of strings.");
  else if (runIds && eventsUrls.length !== runIds.length) reasons.push("events_urls must have one entry per run id.");

  const planKey = typeof body.sandbox_plan_key === "string" && body.sandbox_plan_key.trim() !== "" ? body.sandbox_plan_key : null;
  if (!planKey) reasons.push("sandbox_plan_key must be a non-empty string.");

  const mode: ApprovalMode | null = body.approval_mode === "slack" || body.approval_mode === "sandbox_auto" ? body.approval_mode : null;
  if (!mode) reasons.push('approval_mode must be "slack" or "sandbox_auto".');

  if (scenario === "concurrent_runs" && runIds && runIds.length !== 2) {
    reasons.push(`concurrent_runs should start 2 runs, the backend started ${runIds.length}.`);
  }

  if (reasons.length > 0 || !runIds || !eventsUrls || !planKey || !mode) return { ok: false, reasons };
  return { ok: true, value: { runIds, eventsUrls, sandboxPlanKey: planKey, approvalMode: mode } };
}

export function parseSandboxStatus(body: unknown): Parsed<SandboxStatus> {
  if (!isRecord(body)) return { ok: false, reasons: ["The sandbox status is not a JSON object."] };
  const reasons: string[] = [];
  const available = typeof body.available === "boolean" ? body.available : null;
  if (available === null) reasons.push("available must be true or false.");
  const queueDepth = count(body.queue_depth);
  if (queueDepth === null) reasons.push("queue_depth must be a whole number.");
  const cooldownSeconds = count(body.cooldown_seconds);
  if (cooldownSeconds === null) reasons.push("cooldown_seconds must be a whole number.");
  if (reasons.length > 0 || available === null || queueDepth === null || cooldownSeconds === null) return { ok: false, reasons };
  return { ok: true, value: { available, queueDepth, cooldownSeconds } };
}

/** Maps one sandbox start response to what the page shows. Pure, so every status is testable. */
export function classifySandboxStart(status: number, body: unknown, scenario: SandboxScenario): SandboxStart {
  if (status === 429) return { kind: "rate_limited", retryAfter: isRecord(body) ? count(body.retry_after) : null };
  if (status < 200 || status >= 300) {
    const detail =
      isRecord(body) && typeof body.detail === "string" && body.detail.trim() !== ""
        ? body.detail
        : status === 404
          ? "The backend has no sandbox endpoint."
          : status === 503
            ? "The sandbox is switched off right now."
            : `The backend answered with status ${status}.`;
    return { kind: "unavailable", status, detail };
  }
  const parsed = parseSandboxRuns(body, scenario);
  return parsed.ok ? { kind: "started", runs: parsed.value } : { kind: "invalid", reasons: parsed.reasons };
}

export async function startSandboxRun(scenario: SandboxScenario): Promise<SandboxStart> {
  if (!API_BASE) return { kind: "unconfigured" };
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/sandbox/runs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ scenario }),
      signal: AbortSignal.timeout(START_TIMEOUT_MS),
    });
  } catch (err) {
    console.warn("[PriceQuorum] POST /api/sandbox/runs failed", err);
    return { kind: "unavailable", status: null, detail: `The backend at ${API_BASE} is not reachable or did not answer in time.` };
  }
  const body: unknown = await res.json().catch(() => null);
  return classifySandboxStart(res.status, body, scenario);
}

export async function fetchSandboxStatus(): Promise<SandboxAvailability> {
  if (!API_BASE) return { kind: "unconfigured" };
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/sandbox/status`, { cache: "no-store", signal: AbortSignal.timeout(STATUS_TIMEOUT_MS) });
  } catch (err) {
    console.warn("[PriceQuorum] GET /api/sandbox/status failed", err);
    return { kind: "unavailable", status: null };
  }
  if (!res.ok) return { kind: "unavailable", status: res.status };
  const parsed = parseSandboxStatus(await res.json().catch(() => null));
  return parsed.ok ? { kind: "ready", status: parsed.value } : { kind: "invalid", reasons: parsed.reasons };
}
