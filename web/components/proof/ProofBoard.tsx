"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { API_BASE } from "@/lib/api/client";
import { OUTCOMES } from "@/lib/api/events";
import { parseEvalReport, parseProof, type EvalReport, type Proof } from "@/lib/api/proof";

type State =
  | { kind: "loading" }
  | { kind: "unconfigured" }
  | { kind: "unreachable"; detail: string }
  | { kind: "invalid"; reasons: string[] }
  | { kind: "ready"; proof: Proof; report: EvalReport | null; reportProblem: string | null };

const percent = (p: number) => `${Math.round(p * 1000) / 10}%`;

async function fetchJson(path: string): Promise<{ ok: true; body: unknown } | { ok: false; detail: string }> {
  try {
    const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!res.ok) return { ok: false, detail: `${path} answered with status ${res.status}.` };
    return { ok: true, body: await res.json() };
  } catch {
    return { ok: false, detail: `${path} at ${API_BASE} is not reachable.` };
  }
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-md border border-ink/15 bg-paper-light/70 px-4 py-3">
      <p className="type-display text-3xl text-ink [text-shadow:none]">{value}</p>
      <p className="mt-1 text-sm text-ink-soft">{label}</p>
    </div>
  );
}

export function ProofBoard() {
  const [state, setState] = useState<State>(() => (API_BASE ? { kind: "loading" } : { kind: "unconfigured" }));

  useEffect(() => {
    if (!API_BASE) return;
    let cancelled = false;
    (async () => {
      const [proofRes, reportRes] = await Promise.all([fetchJson("/api/proof"), fetchJson("/api/evals/latest")]);
      if (cancelled) return;
      if (!proofRes.ok) {
        setState({ kind: "unreachable", detail: proofRes.detail });
        return;
      }
      const proof = parseProof(proofRes.body);
      if (!proof.ok) {
        setState({ kind: "invalid", reasons: proof.reasons });
        return;
      }
      let report: EvalReport | null = null;
      let reportProblem: string | null = null;
      if (!reportRes.ok) reportProblem = reportRes.detail;
      else {
        const parsed = parseEvalReport(reportRes.body);
        if (parsed.ok) report = parsed.value;
        else reportProblem = parsed.reasons.join(" ");
      }
      setState({ kind: "ready", proof: proof.value, report, reportProblem });
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="texture-paper relative z-[var(--z-content)] h-fit w-full max-w-[1000px] rounded-[10px] px-6 py-8 text-ink shadow-[0_30px_60px_-30px_rgb(0_0_0/0.65)] sm:px-10">
      <h1 className="type-display text-[clamp(1.8rem,4vw,3rem)] uppercase text-ink [text-shadow:0.04em_0.05em_0_rgb(217_205_173)]">
        The evidence
      </h1>
      <p className="mt-3 max-w-[64ch] leading-relaxed text-ink-soft">
        Every number on this page is recomputed by the backend from its own database when the page loads. Failed
        scenarios are listed with their explanation rather than hidden.
      </p>

      <div className="mt-6">
        {state.kind === "loading" ? <p className="text-ink-soft">Loading the latest results.</p> : null}
        {state.kind === "unconfigured" ? (
          <p role="alert" className="font-semibold text-outcome-needs-human">
            The web app does not know where the backend runs, so there are no results to show yet.
          </p>
        ) : null}
        {state.kind === "unreachable" ? (
          <p role="alert" className="font-semibold text-outcome-needs-human">
            {state.detail} Try again once the backend is online.
          </p>
        ) : null}
        {state.kind === "invalid" ? (
          <div role="alert" className="text-outcome-refused">
            <p className="font-semibold">The proof response could not be used:</p>
            <ul className="mt-2 list-disc pl-5">
              {state.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {state.kind === "ready" ? (
          <div className="space-y-8">
            <div>
              <p className="type-display text-[clamp(2.4rem,6vw,4rem)] leading-none text-ink [text-shadow:none]">
                {state.proof.scenarios.passed} of {state.proof.scenarios.total}
              </p>
              <p className="mt-2 text-lg">
                evaluation scenarios passed
                {state.proof.scenarios.wilson95
                  ? `, 95% interval ${percent(state.proof.scenarios.wilson95[0])} to ${percent(state.proof.scenarios.wilson95[1])}`
                  : ""}
                {state.proof.scenarios.runsPerScenario ? `, ${state.proof.scenarios.runsPerScenario} runs each` : ""}.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <Stat
                value={state.proof.duplicateWritesPrevented === null ? "not reported" : String(state.proof.duplicateWritesPrevented)}
                label="duplicate writes prevented across forced retries"
              />
              <Stat
                value={
                  state.proof.forbiddenRefused
                    ? `${state.proof.forbiddenRefused.refused} of ${state.proof.forbiddenRefused.attempted}`
                    : "not reported"
                }
                label="forbidden actions refused"
              />
              <Stat
                value={
                  state.proof.ledger?.chainIntact === true
                    ? "intact"
                    : state.proof.ledger?.chainIntact === false
                      ? "broken"
                      : "not reported"
                }
                label={`ledger chain${state.proof.ledger?.entries != null ? `, ${state.proof.ledger.entries} entries` : ""}`}
              />
            </div>

            {state.proof.outcomes ? (
              <div>
                <h2 className="text-lg font-semibold">Outcomes across all scenario runs</h2>
                <ul className="mt-2 flex flex-wrap gap-3 text-sm">
                  {OUTCOMES.map((o) => (
                    <li key={o} className="rounded-full border border-ink/20 px-3 py-1">
                      <span className="type-hash">{o}</span> {state.proof.outcomes![o]}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div>
              <h2 className="text-lg font-semibold">Named failures</h2>
              {state.proof.namedFailures.length === 0 ? (
                <p className="mt-1 text-ink-soft">The backend reported no failed scenarios.</p>
              ) : (
                <ul className="mt-2 space-y-2">
                  {state.proof.namedFailures.map((f) => (
                    <li key={f.scenarioId} className="rounded-md border-l-4 border-outcome-refused bg-paper-light/70 px-4 py-2">
                      <span className="type-hash font-semibold">{f.scenarioId}</span>
                      <span className="text-ink-soft">: {f.explanation}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <h2 className="text-lg font-semibold">Every scenario</h2>
              {state.report ? (
                <div className="mt-2 overflow-x-auto" tabIndex={0} role="region" aria-label="Scenario results">
                  <table className="w-full min-w-[640px] border-collapse text-left text-sm">
                    <thead>
                      <tr className="border-b border-ink/20 text-ink-soft">
                        <th scope="col" className="py-2 pr-4 font-semibold">Scenario</th>
                        <th scope="col" className="py-2 pr-4 font-semibold">Expected</th>
                        <th scope="col" className="py-2 pr-4 font-semibold">Observed</th>
                        <th scope="col" className="py-2 pr-4 font-semibold">Result</th>
                        <th scope="col" className="py-2 font-semibold">Run</th>
                      </tr>
                    </thead>
                    <tbody>
                      {state.report.results.map((r) => (
                        <tr key={r.scenarioId} className="border-b border-ink/10 align-top">
                          <td className="type-hash py-2 pr-4">{r.scenarioId}</td>
                          <td className="py-2 pr-4">{r.expectedOutcome ?? "not reported"}</td>
                          <td className="py-2 pr-4">{r.observedOutcome ?? "not reported"}</td>
                          <td className={`py-2 pr-4 font-semibold ${r.passed ? "text-outcome-success" : "text-outcome-refused"}`}>
                            {r.passed ? "passed" : "failed"}
                          </td>
                          <td className="py-2">
                            {r.runId ? (
                              <Link href={`/runs/${encodeURIComponent(r.runId)}`} className="underline underline-offset-4">
                                receipt
                              </Link>
                            ) : (
                              "none"
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="mt-1 text-outcome-needs-human">{state.reportProblem ?? "The per-scenario report is not available."}</p>
              )}
            </div>

            {state.proof.generatedAt || state.proof.commitSha ? (
              <p className="text-sm text-ink-soft">
                Computed {state.proof.generatedAt ?? "at an unreported time"}
                {state.proof.commitSha ? ` for commit ${state.proof.commitSha}` : ""}.
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
