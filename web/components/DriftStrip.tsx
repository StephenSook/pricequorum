"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { API_BASE } from "@/lib/api/client";
import {
  MONITOR_EVENT_TYPES,
  initialMonitorView,
  parseMonitorEvent,
  reduceMonitor,
  summarizeMonitor,
  type MonitorConnection,
  type MonitorView,
} from "@/lib/api/monitor";

const TONE = {
  watching: "bg-forest/95 text-paper-deep",
  clear: "bg-forest/95 text-paper-light",
  drift: "bg-outcome-refused text-paper-light",
} as const;

/**
 * A thin strip fed by the drift monitor. It stays hidden until the monitor stream has opened, and it
 * never says there is no drift before the monitor reports a completed check.
 */
export function DriftStrip() {
  const [connection, setConnection] = useState<MonitorConnection | null>(null);
  const [view, setView] = useState<MonitorView>(initialMonitorView);
  const [invalid, setInvalid] = useState(0);

  useEffect(() => {
    if (!API_BASE) return;
    const source = new EventSource(`${API_BASE}/api/monitor/events`);
    let cancelled = false;
    let opened = false;

    const handlers = [...MONITOR_EVENT_TYPES, "message"].map((name) => {
      const handler = (message: MessageEvent<string>) => {
        if (cancelled) return;
        const event = parseMonitorEvent(name, message.data);
        if (!event) {
          setInvalid((n) => n + 1);
          return;
        }
        setView((prev) => reduceMonitor(prev, event));
      };
      return [name, handler] as const;
    });
    for (const [name, handler] of handlers) source.addEventListener(name, handler as EventListener);

    source.onopen = () => {
      if (cancelled) return;
      opened = true;
      setConnection("open");
    };
    source.onerror = () => {
      if (cancelled || !opened) return;
      setConnection(source.readyState === EventSource.CLOSED ? "closed" : "reconnecting");
    };

    return () => {
      cancelled = true;
      source.onopen = null;
      source.onerror = null;
      for (const [name, handler] of handlers) source.removeEventListener(name, handler as EventListener);
      source.close();
    };
  }, []);

  if (connection === null) return null;
  const summary = summarizeMonitor(view, connection);

  return (
    <div
      role="status"
      className={`fixed inset-x-0 bottom-0 z-[var(--z-overlay)] flex flex-wrap items-center justify-center gap-x-4 gap-y-1 px-4 py-2 text-center text-sm ${TONE[summary.tone]}`}
    >
      <span>{summary.text}</span>
      {summary.healed ? (
        <span>
          Healed {summary.healed.app} for {summary.healed.planKey}:{" "}
          <Link href={`/runs/${encodeURIComponent(summary.healed.runId)}`} className="font-semibold underline underline-offset-4">
            see the run
          </Link>
        </span>
      ) : null}
      {invalid > 0 ? (
        <span>
          {invalid} malformed monitor message{invalid === 1 ? "" : "s"} ignored
        </span>
      ) : null}
    </div>
  );
}
