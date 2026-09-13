import { describe, expect, it } from "vitest";

import { classifySandboxStart, parseSandboxRuns, parseSandboxStatus } from "@/lib/api/sandbox";

const ID_A = "3f7c1a52-0000-4000-8000-00000000000a";
const ID_B = "3f7c1a52-0000-4000-8000-00000000000b";

const started = (overrides: Record<string, unknown> = {}) => ({
  run_ids: [ID_A],
  events_urls: [`/api/runs/${ID_A}/events`],
  sandbox_plan_key: "judge_pro",
  approval_mode: "sandbox_auto",
  ...overrides,
});

describe("parseSandboxRuns", () => {
  it("accepts a contract-shaped response", () => {
    expect(parseSandboxRuns(started(), "happy_path")).toEqual({
      ok: true,
      value: { runIds: [ID_A], eventsUrls: [`/api/runs/${ID_A}/events`], sandboxPlanKey: "judge_pro", approvalMode: "sandbox_auto" },
    });
  });

  it("expects exactly two distinct runs for concurrent_runs", () => {
    const two = started({ run_ids: [ID_A, ID_B], events_urls: ["a", "b"], approval_mode: "slack" });
    expect(parseSandboxRuns(two, "concurrent_runs").ok).toBe(true);
    expect(parseSandboxRuns(started(), "concurrent_runs").ok).toBe(false);
    expect(parseSandboxRuns(started({ run_ids: [ID_A, ID_A], events_urls: ["a", "b"] }), "concurrent_runs").ok).toBe(false);
  });

  it("rejects missing, malformed or mismatched fields", () => {
    expect(parseSandboxRuns(null, "happy_path").ok).toBe(false);
    expect(parseSandboxRuns(started({ run_ids: [] }), "happy_path").ok).toBe(false);
    expect(parseSandboxRuns(started({ run_ids: ["not a run id!"] }), "happy_path").ok).toBe(false);
    expect(parseSandboxRuns(started({ events_urls: [] }), "happy_path").ok).toBe(false);
    expect(parseSandboxRuns(started({ sandbox_plan_key: "  " }), "happy_path").ok).toBe(false);
    expect(parseSandboxRuns(started({ approval_mode: "operator" }), "happy_path").ok).toBe(false);
  });
});

describe("parseSandboxStatus", () => {
  it("accepts whole numbers and a boolean", () => {
    expect(parseSandboxStatus({ available: true, queue_depth: 0, cooldown_seconds: 30 })).toEqual({
      ok: true,
      value: { available: true, queueDepth: 0, cooldownSeconds: 30 },
    });
  });

  it("rejects negative, fractional or missing values", () => {
    expect(parseSandboxStatus({ available: true, queue_depth: -1, cooldown_seconds: 0 }).ok).toBe(false);
    expect(parseSandboxStatus({ available: true, queue_depth: 1, cooldown_seconds: 2.5 }).ok).toBe(false);
    expect(parseSandboxStatus({ available: "yes", queue_depth: 1, cooldown_seconds: 0 }).ok).toBe(false);
    expect(parseSandboxStatus({}).ok).toBe(false);
  });
});

describe("classifySandboxStart", () => {
  it("starts on a 2xx with a valid body and reports an invalid body as invalid", () => {
    expect(classifySandboxStart(202, started(), "happy_path")).toMatchObject({ kind: "started" });
    expect(classifySandboxStart(202, null, "happy_path")).toMatchObject({ kind: "invalid" });
    expect(classifySandboxStart(202, started({ approval_mode: "robot" }), "happy_path")).toMatchObject({ kind: "invalid" });
  });

  it("reads retry_after from a 429 and does not invent one when it is missing", () => {
    expect(classifySandboxStart(429, { error: "rate_limited", retry_after: 42 }, "drift")).toEqual({ kind: "rate_limited", retryAfter: 42 });
    expect(classifySandboxStart(429, { error: "rate_limited" }, "drift")).toEqual({ kind: "rate_limited", retryAfter: null });
  });

  it("reports the exact status when the sandbox is unavailable", () => {
    expect(classifySandboxStart(404, null, "happy_path")).toEqual({ kind: "unavailable", status: 404, detail: "The backend has no sandbox endpoint." });
    expect(classifySandboxStart(503, { detail: "Sandbox reset in progress." }, "happy_path")).toEqual({
      kind: "unavailable",
      status: 503,
      detail: "Sandbox reset in progress.",
    });
    expect(classifySandboxStart(500, {}, "happy_path")).toEqual({ kind: "unavailable", status: 500, detail: "The backend answered with status 500." });
  });
});
