"use client";

import { useEffect, useState } from "react";

import { useRouteReady } from "@/components/HydrationMark";
import { RunStage } from "@/components/RunStage";
import { API_BASE } from "@/lib/api/client";
import {
  SANDBOX_SCENARIOS,
  fetchSandboxStatus,
  startSandboxRun,
  type SandboxAvailability,
  type SandboxRuns,
  type SandboxScenario,
} from "@/lib/api/sandbox";

const SCENARIOS: Record<SandboxScenario, { title: string; tests: string }> = {
  happy_path: {
    title: "A normal price change",
    tests: "whether a change is approved, written once to all three apps and read back to a signed receipt.",
  },
  timeout_after_commit: {
    title: "A timeout after Stripe accepts the write",
    tests: "whether the agent reads Stripe back and skips the retry when the write already landed.",
  },
  prompt_injection: {
    title: "Instructions hidden in a Notion record",
    tests: "whether text read from an app is treated as data and an unsafe action is refused with a remedy.",
  },
  locked_record: {
    title: "A locked Airtable record",
    tests: "whether the run stops with a remedy instead of forcing a write to a locked record.",
  },
  chain_tamper: {
    title: "An edited ledger entry",
    tests: "whether verification names the edited entry in a sandbox copy of the ledger.",
  },
  concurrent_runs: {
    title: "Two changes to the same plan at once",
    tests: "whether only one run writes and the other is refused cleanly.",
  },
  drift: {
    title: "A price edited by hand in Notion",
    tests: "whether the drift monitor notices Notion disagreeing with Stripe and heals it from Stripe.",
  },
};

type Trial =
  | { scenario: SandboxScenario; kind: "starting" }
  | { scenario: SandboxScenario; kind: "started"; runs: SandboxRuns }
  | { scenario: SandboxScenario; kind: "rate_limited"; until: number | null }
  | { scenario: SandboxScenario; kind: "unavailable"; status: number | null; detail: string }
  | { scenario: SandboxScenario; kind: "invalid"; reasons: string[] };

/** Wall-clock time for the rate-limit countdown, read only inside event handlers and timers. */
function currentTime(): number {
  return Date.now();
}

function availabilityText(availability: SandboxAvailability | null): string {
  if (!availability) return "Checking whether the sandbox is open.";
  switch (availability.kind) {
    case "unconfigured":
      return "The web app does not know where the backend runs, so the sandbox cannot start runs yet.";
    case "unavailable":
      return availability.status === null
        ? "The sandbox status could not be reached."
        : `The sandbox status endpoint answered with status ${availability.status}.`;
    case "invalid":
      return "The sandbox status response could not be used.";
    case "ready": {
      const { available, queueDepth, cooldownSeconds } = availability.status;
      const queued = `${queueDepth} run${queueDepth === 1 ? "" : "s"} queued`;
      if (!available) return `Sandbox paused, ${queued}. Try again in ${cooldownSeconds} s.`;
      return `Sandbox open, ${queued}${cooldownSeconds > 0 ? `, ${cooldownSeconds} s between runs` : ""}.`;
    }
  }
}

export function BreakPanel() {
  useRouteReady("break");
  const [availability, setAvailability] = useState<SandboxAvailability | null>(() => (API_BASE ? null : { kind: "unconfigured" }));
  const [trial, setTrial] = useState<Trial | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!API_BASE) return;
    let cancelled = false;
    fetchSandboxStatus().then((result) => {
      if (!cancelled) setAvailability(result);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const until = trial?.kind === "rate_limited" ? trial.until : null;
  useEffect(() => {
    if (until === null) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [until]);
  const remaining = until === null ? 0 : Math.max(0, Math.ceil((until - now) / 1000));
  const busy = trial?.kind === "starting" || remaining > 0;

  const run = async (scenario: SandboxScenario) => {
    setTrial({ scenario, kind: "starting" });
    const result = await startSandboxRun(scenario);
    const at = currentTime();
    setNow(at);
    switch (result.kind) {
      case "started":
        setTrial({ scenario, kind: "started", runs: result.runs });
        break;
      case "rate_limited":
        setTrial({ scenario, kind: "rate_limited", until: result.retryAfter === null ? null : at + result.retryAfter * 1000 });
        break;
      case "unavailable":
        setTrial({ scenario, kind: "unavailable", status: result.status, detail: result.detail });
        break;
      case "invalid":
        setTrial({ scenario, kind: "invalid", reasons: result.reasons });
        break;
      case "unconfigured":
        setTrial(null);
        setAvailability({ kind: "unconfigured" });
        return;
    }
    const status = await fetchSandboxStatus();
    setAvailability(status);
  };

  return (
    <div className="relative z-[var(--z-content)] flex w-full max-w-[1400px] flex-col items-center gap-10">
      <article className="texture-paper h-fit w-full max-w-[960px] rounded-[10px] px-6 py-8 text-ink shadow-[0_30px_60px_-30px_rgb(0_0_0/0.65)] sm:px-10">
        <h1 className="type-display text-[clamp(1.8rem,4vw,3rem)] uppercase text-ink [text-shadow:0.04em_0.05em_0_rgb(217_205_173)]">
          Try to break it
        </h1>
        <p className="mt-3 max-w-[64ch] leading-relaxed text-ink-soft">
          Each scenario starts a sandbox run built to go wrong in one specific way. Every chapter that appears below comes from
          the backend&apos;s own events for that run.
        </p>
        <p role="status" className="mt-4 text-sm font-semibold text-ink">
          {availabilityText(availability)}
        </p>

        <ul className="mt-6 grid gap-3 sm:grid-cols-2">
          {SANDBOX_SCENARIOS.map((scenario) => {
            const copy = SCENARIOS[scenario];
            const starting = trial?.kind === "starting" && trial.scenario === scenario;
            return (
              <li key={scenario} className="flex flex-col justify-between gap-3 rounded-md border border-ink/15 bg-paper-light/70 p-4">
                <div>
                  <p className="font-semibold">{copy.title}</p>
                  <p className="mt-1 text-sm text-ink-soft">Tests {copy.tests}</p>
                </div>
                <button
                  type="button"
                  onClick={() => void run(scenario)}
                  disabled={!API_BASE || busy}
                  aria-label={`Run ${copy.title}`}
                  className="min-h-11 w-fit cursor-pointer rounded-md bg-forest px-4 py-2 font-semibold text-paper-light transition-colors duration-200 hover:bg-olive disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {starting ? "Running" : "Run"}
                </button>
              </li>
            );
          })}
        </ul>

        <TrialMessage trial={trial} remaining={remaining} />
      </article>

      {trial?.kind === "started" ? (
        <section aria-label="Sandbox runs" className={`grid w-full gap-6 ${trial.runs.runIds.length > 1 ? "lg:grid-cols-2" : ""}`}>
          {trial.runs.runIds.map((runId) => (
            <RunStage key={runId} runId={runId} />
          ))}
        </section>
      ) : null}
    </div>
  );
}

function TrialMessage({ trial, remaining }: { trial: Trial | null; remaining: number }) {
  if (!trial) return null;
  const title = SCENARIOS[trial.scenario].title;
  switch (trial.kind) {
    case "starting":
      return (
        <p role="status" className="mt-6 text-ink-soft">
          Starting: {title}.
        </p>
      );
    case "rate_limited":
      return (
        <p role="alert" className="mt-6 font-semibold text-outcome-needs-human">
          The sandbox is rate limited.{" "}
          {trial.until === null ? "It did not say when to try again." : remaining > 0 ? `Try again in ${remaining} s.` : "You can try again now."}
        </p>
      );
    case "unavailable":
      return (
        <p role="alert" className="mt-6 font-semibold text-outcome-needs-human">
          {trial.detail}
          {trial.status !== null ? ` (status ${trial.status})` : ""}
        </p>
      );
    case "invalid":
      return (
        <div role="alert" className="mt-6 text-outcome-refused">
          <p className="font-semibold">The sandbox response could not be used:</p>
          <ul className="mt-2 list-disc pl-5">
            {trial.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      );
    case "started":
      return (
        <div role="status" className="mt-6 space-y-1 text-sm">
          <p className="font-semibold">Started: {title}.</p>
          <p>
            {trial.runs.approvalMode === "sandbox_auto"
              ? "Approval in this run is automatic: the sandbox auto-approver stands in, not a person."
              : "Approval goes to a person in Slack before anything is written."}
          </p>
          <p className="text-ink-soft">
            Sandbox plan <span className="type-hash">{trial.runs.sandboxPlanKey}</span>
            {trial.runs.runIds.length > 1 ? `, ${trial.runs.runIds.length} runs started together` : ""}.
          </p>
        </div>
      );
  }
}
