/**
 * Parsers for GET /api/proof and GET /api/evals/latest (docs/contracts/api.md).
 *
 * The headline number must come from the backend exactly as reported. Required fields are
 * validated; optional fields the backend omitted stay null and are shown as "not reported",
 * never filled with zero.
 */
import { OUTCOMES, type Outcome } from "@/lib/api/events";

export type Proof = {
  generatedAt: string | null;
  commitSha: string | null;
  scenarios: { passed: number; total: number; wilson95: [number, number] | null; runsPerScenario: number | null };
  outcomes: Record<Outcome, number> | null;
  duplicateWritesPrevented: number | null;
  forbiddenRefused: { refused: number; attempted: number } | null;
  namedFailures: { scenarioId: string; explanation: string }[];
  ledger: { entries: number | null; chainIntact: boolean | null; signatureValid: boolean | null } | null;
  liveRuns: { total: number; success: number } | null;
  lastEvalRunAt: string | null;
};

export type EvalResult = {
  scenarioId: string;
  description: string | null;
  expectedOutcome: Outcome | null;
  observedOutcome: Outcome | null;
  passed: boolean;
  runId: string | null;
  detail: string | null;
};

export type EvalReport = { runAt: string | null; commitSha: string | null; results: EvalResult[] };

type Parsed<T> = { ok: true; value: T } | { ok: false; reasons: string[] };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const count = (value: unknown): number | null => (Number.isInteger(value) && (value as number) >= 0 ? (value as number) : null);
const text = (value: unknown): string | null => (typeof value === "string" ? value : null);
const flag = (value: unknown): boolean | null => (typeof value === "boolean" ? value : null);
const outcome = (value: unknown): Outcome | null =>
  typeof value === "string" && (OUTCOMES as readonly string[]).includes(value) ? (value as Outcome) : null;

export function parseProof(body: unknown): Parsed<Proof> {
  if (!isRecord(body)) return { ok: false, reasons: ["The proof response is not a JSON object."] };
  const reasons: string[] = [];

  const scenarios = isRecord(body.scenarios) ? body.scenarios : null;
  const passed = scenarios ? count(scenarios.passed) : null;
  const total = scenarios ? count(scenarios.total) : null;
  if (passed === null || total === null) reasons.push("scenarios.passed and scenarios.total must be whole numbers.");
  else if (passed > total) reasons.push(`scenarios.passed (${passed}) is greater than scenarios.total (${total}).`);

  let wilson95: [number, number] | null = null;
  if (scenarios && scenarios.wilson_95 !== undefined && scenarios.wilson_95 !== null) {
    const w = scenarios.wilson_95;
    if (Array.isArray(w) && w.length === 2 && w.every((n) => typeof n === "number" && n >= 0 && n <= 1) && w[0] <= w[1]) {
      wilson95 = [w[0], w[1]];
    } else {
      reasons.push("scenarios.wilson_95 must be two proportions between 0 and 1, low then high.");
    }
  }

  let outcomes: Record<Outcome, number> | null = null;
  if (isRecord(body.outcomes)) {
    const values = OUTCOMES.map((o) => count((body.outcomes as Record<string, unknown>)[o]));
    if (values.every((v) => v !== null)) outcomes = Object.fromEntries(OUTCOMES.map((o, i) => [o, values[i]])) as Record<Outcome, number>;
  }

  const refusedBlock = isRecord(body.forbidden_actions_refused) ? body.forbidden_actions_refused : null;
  const refused = refusedBlock ? count(refusedBlock.refused) : null;
  const attempted = refusedBlock ? count(refusedBlock.attempted) : null;

  const namedFailures = Array.isArray(body.named_failures)
    ? body.named_failures.flatMap((f) =>
        isRecord(f) && typeof f.scenario_id === "string" && typeof f.explanation === "string"
          ? [{ scenarioId: f.scenario_id, explanation: f.explanation }]
          : [],
      )
    : [];

  const ledgerBlock = isRecord(body.ledger) ? body.ledger : null;
  const liveBlock = isRecord(body.live_runs) ? body.live_runs : null;
  const liveTotal = liveBlock ? count(liveBlock.total) : null;
  const liveSuccess = liveBlock ? count(liveBlock.success) : null;

  if (reasons.length > 0 || passed === null || total === null) return { ok: false, reasons };
  return {
    ok: true,
    value: {
      generatedAt: text(body.generated_at),
      commitSha: text(body.commit_sha),
      scenarios: { passed, total, wilson95, runsPerScenario: scenarios ? count(scenarios.runs_per_scenario) : null },
      outcomes,
      duplicateWritesPrevented: count(body.duplicate_writes_prevented),
      forbiddenRefused: refused !== null && attempted !== null ? { refused, attempted } : null,
      namedFailures,
      ledger: ledgerBlock
        ? { entries: count(ledgerBlock.entries), chainIntact: flag(ledgerBlock.chain_intact), signatureValid: flag(ledgerBlock.signature_valid) }
        : null,
      liveRuns: liveTotal !== null && liveSuccess !== null ? { total: liveTotal, success: liveSuccess } : null,
      lastEvalRunAt: text(body.last_eval_run_at),
    },
  };
}

export function parseEvalReport(body: unknown): Parsed<EvalReport> {
  if (!isRecord(body)) return { ok: false, reasons: ["The eval report is not a JSON object."] };
  if (!Array.isArray(body.results)) return { ok: false, reasons: ["The eval report has no results array."] };
  const reasons: string[] = [];
  const results: EvalResult[] = [];
  body.results.forEach((r, index) => {
    if (!isRecord(r) || typeof r.scenario_id !== "string" || typeof r.passed !== "boolean") {
      reasons.push(`Result at position ${index} is missing scenario_id or passed.`);
      return;
    }
    results.push({
      scenarioId: r.scenario_id,
      description: text(r.description),
      expectedOutcome: outcome(r.expected_outcome),
      observedOutcome: outcome(r.observed_outcome),
      passed: r.passed,
      runId: text(r.run_id),
      detail: text(r.detail),
    });
  });
  if (reasons.length > 0) return { ok: false, reasons };
  return { ok: true, value: { runAt: text(body.run_at), commitSha: text(body.commit_sha), results } };
}
