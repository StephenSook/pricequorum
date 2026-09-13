"use client";

import { useEffect, useRef } from "react";

import { Approve } from "@/components/chapters/Approve";
import { Migrate } from "@/components/chapters/Migrate";
import { Receipt } from "@/components/chapters/Receipt";
import { Resolve } from "@/components/chapters/Resolve";
import { Verify } from "@/components/chapters/Verify";
import { currentChapter } from "@/lib/api/events";
import { prefersReducedMotion } from "@/lib/motion/prefersReducedMotion";
import { useRunEvents, type StreamState } from "@/lib/api/useRunEvents";

const STREAM_LABEL: Record<StreamState, string> = {
  idle: "Not connected",
  connecting: "Connecting to the run",
  open: "Live",
  reconnecting: "Reconnecting, no events lost",
  closed: "Run finished",
  unavailable: "Backend address not configured",
};

/**
 * The live run. Each chapter appears only once the backend has reported the event that
 * belongs to it, so the page never runs ahead of what actually happened.
 */
export function RunStage({ runId }: { runId: string }) {
  const { view, stream, invalidMessages } = useRunEvents(runId);
  const chapter = view ? currentChapter(view) : "waiting";
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "end" });
  }, [chapter]);

  if (!view) return null;

  const showResolve = Boolean(view.intent || view.resolution || view.policy);
  const showApprove = Boolean(view.approval || view.policy);
  const showMigrate = view.ledger.length > 0;
  const showVerify = view.readbacks.length > 0 || view.invariants.length > 0;
  const showReceipt = Boolean(view.outcome);

  return (
    <div className="relative z-[var(--z-content)] flex w-full flex-col items-center gap-8 px-4 pb-24 pt-10">
      <p role="status" className="flex items-center gap-2 rounded-full bg-forest/90 px-4 py-2 text-sm text-paper-deep">
        <span
          aria-hidden="true"
          className={`h-2 w-2 rounded-full ${stream === "open" ? "bg-outcome-success" : stream === "closed" ? "bg-brass" : "bg-outcome-needs-human"}`}
        />
        {STREAM_LABEL[stream]}
        <span className="type-hash text-xs text-paper-deep/70">run {runId.slice(0, 8)}</span>
      </p>

      {chapter === "waiting" ? (
        <p role={stream === "unavailable" ? "alert" : undefined} className="rounded-lg bg-forest/85 px-6 py-5 text-center text-paper-light">
          {stream === "unavailable"
            ? "The backend address is not configured, so this run cannot be loaded."
            : stream === "open"
              ? "Connected. Waiting for the first event from the backend."
              : stream === "reconnecting"
                ? "The connection dropped. Reconnecting without losing events."
                : stream === "closed"
                  ? "The stream closed before any event arrived."
                  : "Connecting to the run."}
        </p>
      ) : null}

      {showResolve ? <Resolve view={view} /> : null}
      {showApprove ? <Approve view={view} /> : null}
      {showMigrate ? <Migrate view={view} /> : null}
      {showVerify ? <Verify view={view} /> : null}
      {showReceipt ? <Receipt view={view} /> : null}

      {view.unrecognized.length > 0 || invalidMessages > 0 ? (
        <p className="max-w-xl text-center text-xs text-paper-deep/80">
          {view.unrecognized.length} event{view.unrecognized.length === 1 ? "" : "s"} this page does not display yet
          {invalidMessages > 0 ? `, ${invalidMessages} malformed message${invalidMessages === 1 ? "" : "s"} ignored` : ""}.
        </p>
      ) : null}
      <div ref={end} />
    </div>
  );
}
