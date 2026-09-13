"use client";

import { useEffect, useState } from "react";

import { ChapterFrame } from "@/components/chapters/ChapterFrame";
import type { RunView } from "@/lib/api/events";

const MODE_LABEL: Record<string, string> = {
  slack: "Decided in Slack",
  operator: "Decided with the operator fallback, not Slack",
  sandbox_auto: "Sandbox auto-approver for the public demo, not a person",
};

const DECISION_STYLE: Record<string, string> = {
  APPROVED: "border-outcome-success text-outcome-success",
  DENIED: "border-outcome-refused text-outcome-refused",
  EXPIRED: "border-outcome-needs-human text-outcome-needs-human",
  PENDING: "border-ink-soft text-ink-soft",
};

function useRemaining(expiresAt: string | null, active: boolean): string | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active || !expiresAt) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active, expiresAt]);
  if (!expiresAt) return null;
  const end = Date.parse(expiresAt);
  if (Number.isNaN(end)) return null;
  const seconds = Math.max(0, Math.round((end - now) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function Approve({ view }: { view: RunView }) {
  const { approval, policy } = view;
  const pending = approval?.phase === "requested";
  const remaining = useRemaining(approval?.expiresAt ?? null, pending);
  const decision = approval?.decision ?? null;
  const refusedByPolicy = policy?.decision === "REFUSED";

  return (
    <ChapterFrame
      index={2}
      title="Ask a person first"
      tone="bordeaux"
      aside={
        policy ? (
          <div className="rounded-md border border-ink/15 bg-paper-light/60 p-4 text-sm">
            <p className="text-ink-soft">Policy check</p>
            <p className="mt-1 font-semibold">{policy.decision ?? "not reported"}</p>
            {policy.rule ? <p className="type-hash mt-1 text-ink-soft">{policy.rule}</p> : null}
            {policy.detail ? <p className="mt-2">{policy.detail}</p> : null}
          </div>
        ) : null
      }
    >
      {approval ? (
        <article className="max-w-[560px] rounded-lg border border-ink/15 bg-white/80 p-5 shadow-sm">
          <header className="flex items-center gap-3">
            <span aria-hidden="true" className="flex h-9 w-9 items-center justify-center rounded-md bg-olive font-bold text-paper-light">
              PQ
            </span>
            <div>
              <p className="font-bold">PriceQuorum</p>
              <p className="text-sm text-ink-soft">{approval.mode ? (MODE_LABEL[approval.mode] ?? approval.mode) : "approval channel not reported"}</p>
            </div>
          </header>
          <p className="mt-4 text-lg">{approval.summary ?? "Summary not reported"}</p>

          <div className="mt-5 flex flex-wrap items-center gap-4">
            <span
              className={`type-kicker inline-block rotate-[-4deg] rounded border-[3px] px-3 py-1 text-base ${DECISION_STYLE[decision ?? "PENDING"] ?? DECISION_STYLE.PENDING}`}
            >
              {decision ? decision.toLowerCase() : "waiting"}
            </span>
            {pending && remaining ? <span className="text-ink-soft">expires in {remaining}</span> : null}
            {approval.approverDisplay ? <span className="text-ink-soft">by {approval.approverDisplay}</span> : null}
          </div>
        </article>
      ) : refusedByPolicy ? (
        <div role="alert" className="rounded-md border-2 border-outcome-refused/60 bg-outcome-refused/10 px-4 py-3">
          <p className="font-semibold text-outcome-refused">Refused before asking anyone.</p>
          {policy?.remedy ? <p className="mt-1">{policy.remedy}</p> : null}
        </div>
      ) : (
        <p className="text-ink-soft">No approval requested yet.</p>
      )}
    </ChapterFrame>
  );
}
