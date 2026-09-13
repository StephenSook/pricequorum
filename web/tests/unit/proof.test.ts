import { describe, expect, it } from "vitest";

import { parseEvalReport, parseProof } from "@/lib/api/proof";

const VALID = {
  generated_at: "2026-09-13T21:00:00Z",
  commit_sha: "abc1234",
  scenarios: { passed: 19, total: 20, wilson_95: [0.76, 0.99], runs_per_scenario: 3 },
  outcomes: { SUCCESS: 9, PARTIAL: 3, REFUSED: 5, NEEDS_HUMAN: 3 },
  duplicate_writes_prevented: 4,
  forbidden_actions_refused: { refused: 5, attempted: 5 },
  named_failures: [{ scenario_id: "stale_read", explanation: "cache served before the fresh read" }],
  ledger: { entries: 137, chain_intact: true, signature_valid: true },
  live_runs: { total: 2, success: 2 },
  last_eval_run_at: "2026-09-13T20:55:00Z",
};

describe("parseProof", () => {
  it("maps a complete proof response", () => {
    const parsed = parseProof(VALID);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.scenarios).toEqual({ passed: 19, total: 20, wilson95: [0.76, 0.99], runsPerScenario: 3 });
    expect(parsed.value.forbiddenRefused).toEqual({ refused: 5, attempted: 5 });
    expect(parsed.value.namedFailures).toEqual([{ scenarioId: "stale_read", explanation: "cache served before the fresh read" }]);
  });

  it("leaves omitted optional fields null instead of reporting zero", () => {
    const parsed = parseProof({ scenarios: { passed: 3, total: 4 } });
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.duplicateWritesPrevented).toBeNull();
    expect(parsed.value.forbiddenRefused).toBeNull();
    expect(parsed.value.outcomes).toBeNull();
    expect(parsed.value.scenarios.wilson95).toBeNull();
  });

  it("rejects a pass count larger than the total", () => {
    expect(parseProof({ scenarios: { passed: 21, total: 20 } }).ok).toBe(false);
  });

  it("rejects a missing or fractional pass count", () => {
    expect(parseProof({ scenarios: { total: 20 } }).ok).toBe(false);
    expect(parseProof({ scenarios: { passed: 19.5, total: 20 } }).ok).toBe(false);
  });

  it("keeps a missing named failures list distinct from an empty one", () => {
    const missing = parseProof({ scenarios: { passed: 19, total: 20 } });
    const empty = parseProof({ scenarios: { passed: 20, total: 20 }, named_failures: [] });
    expect(missing.ok && missing.value.namedFailures).toBeNull();
    expect(empty.ok && empty.value.namedFailures).toEqual([]);
  });

  it("rejects a malformed named failure and more refusals than attempts", () => {
    expect(parseProof({ scenarios: { passed: 1, total: 2 }, named_failures: [{ scenario_id: "x" }] }).ok).toBe(false);
    expect(parseProof({ scenarios: { passed: 1, total: 2 }, named_failures: "none" }).ok).toBe(false);
    expect(parseProof({ scenarios: { passed: 1, total: 2 }, forbidden_actions_refused: { refused: 3, attempted: 2 } }).ok).toBe(false);
  });

  it("rejects a confidence interval outside 0 to 1 or out of order", () => {
    expect(parseProof({ scenarios: { passed: 1, total: 2, wilson_95: [0.9, 0.2] } }).ok).toBe(false);
    expect(parseProof({ scenarios: { passed: 1, total: 2, wilson_95: [0.1, 1.4] } }).ok).toBe(false);
  });
});

describe("parseEvalReport", () => {
  it("maps results and keeps unknown outcomes as null", () => {
    const parsed = parseEvalReport({
      run_at: "t",
      results: [
        { scenario_id: "happy_path", passed: true, expected_outcome: "SUCCESS", observed_outcome: "SUCCESS", run_id: "r1" },
        { scenario_id: "stale_read", passed: false, expected_outcome: "PARTIAL", observed_outcome: "DONE", detail: "why" },
      ],
    });
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.results[1]).toMatchObject({ scenarioId: "stale_read", passed: false, observedOutcome: null, detail: "why" });
  });

  it("rejects results missing scenario_id or passed", () => {
    expect(parseEvalReport({ results: [{ scenario_id: "x" }] }).ok).toBe(false);
    expect(parseEvalReport({}).ok).toBe(false);
  });
});
