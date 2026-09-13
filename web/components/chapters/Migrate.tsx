import { ChapterFrame } from "@/components/chapters/ChapterFrame";
import { CopyHash } from "@/components/ui/CopyHash";
import type { LedgerStep, RunView } from "@/lib/api/events";

const FAULT_TEXT: Record<string, string> = {
  timeout: "The call timed out after the request was sent",
  rate_limit: "Rate limited by the app",
  conflict_409: "Another request held the same idempotency key",
  server_5xx: "The app returned a server error",
};

function StepRow({ step }: { step: LedgerStep }) {
  return (
    <li className="border-b border-olive/20 py-3 last:border-b-0">
      <div className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 sm:grid-cols-[2.5rem_7rem_minmax(0,1fr)_7rem]">
        <span className="type-hash text-ink-soft">{step.stepNo ?? "?"}</span>
        <span className="font-semibold capitalize">{step.app ?? "unknown app"}</span>
        <span className="col-start-2 min-w-0 sm:col-start-auto">
          <span className="block">{step.action?.replaceAll("_", " ") ?? "action not reported"}</span>
          <span className="type-hash block truncate text-xs text-ink-soft" title={step.idempotencyKey ?? undefined}>
            {step.idempotencyKey ?? "no idempotency key reported"}
          </span>
        </span>
        <span
          className={`col-start-2 text-sm font-semibold sm:col-start-auto sm:text-right ${step.state === "completed" ? "text-outcome-success" : "text-outcome-needs-human"}`}
        >
          {step.state === "completed" ? "written" : "pending"}
        </span>
      </div>

      {step.fault ? (
        <div role="status" className="mt-3 rounded-md bg-outcome-refused/10 px-3 py-2 text-sm sm:ml-[3.25rem]">
          <p className="font-semibold text-outcome-refused">
            {step.fault.kind ? (FAULT_TEXT[step.fault.kind] ?? step.fault.kind) : "Fault reported"}
            {step.fault.injected ? " (injected on purpose for this run)" : ""}
          </p>
          {step.recovery ? (
            <p className="mt-1">
              {step.recovery.foundLanded
                ? "Read the app back: the write had landed, so it was not sent again."
                : "Read the app back: the write had not landed, so it was retried with the same key."}
            </p>
          ) : (
            <p className="mt-1 text-ink-soft">Reading the app back to learn whether the write landed.</p>
          )}
        </div>
      ) : null}

      {step.entryHash ? (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-soft sm:ml-[3.25rem]">
          ledger entry <CopyHash value={step.entryHash} label={`ledger entry ${step.stepNo ?? ""}`} />
        </div>
      ) : null}
    </li>
  );
}

export function Migrate({ view }: { view: RunView }) {
  const steps = [...view.ledger].sort((a, b) => (a.stepNo ?? a.ledgerId) - (b.stepNo ?? b.ledgerId));
  const written = steps.filter((s) => s.state === "completed").length;

  return (
    <ChapterFrame
      index={3}
      title="Write each change exactly once"
      tone="brown"
      aside={
        <div className="rounded-md border border-ink/15 bg-paper-light/60 p-4">
          <p className="type-display text-4xl text-olive [text-shadow:none]">
            {written}/{steps.length}
          </p>
          <p className="mt-1 text-sm text-ink-soft">
            steps written. Each row is recorded as pending before the app is called.
          </p>
        </div>
      }
    >
      <ol className="rounded-md border border-olive/25 bg-[repeating-linear-gradient(transparent_0_calc(3rem-1px),rgb(70_80_22/0.08)_calc(3rem-1px)_3rem)] bg-paper-light/70 px-4">
        {steps.map((step) => (
          <StepRow key={step.ledgerId} step={step} />
        ))}
      </ol>
    </ChapterFrame>
  );
}
