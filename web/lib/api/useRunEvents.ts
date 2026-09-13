"use client";

import { useEffect, useReducer, useState } from "react";

import { API_BASE } from "@/lib/api/client";
import { KNOWN_EVENT_TYPES, initialRunView, parseEnvelope, reduceRun, type Envelope, type RunView } from "@/lib/api/events";

export type StreamState = "idle" | "connecting" | "open" | "reconnecting" | "closed" | "unavailable";

/** Starts a fresh view whenever an event belongs to a different run than the one held. */
function reducer(view: RunView | null, envelope: Envelope): RunView {
  const base = view && view.runId === envelope.runId ? view : initialRunView(envelope.runId);
  return reduceRun(base, envelope);
}

type Keyed<T> = { runId: string; value: T };

/**
 * Subscribes to `GET /api/runs/{id}/events`. The browser's EventSource resends
 * `Last-Event-ID` on reconnect, and the reducer drops any replayed sequence numbers,
 * so a dropped connection never duplicates or skips a chapter.
 *
 * State only changes inside EventSource callbacks; everything else is derived from
 * `runId`, so switching runs never shows the previous run's events or stream status.
 */
export function useRunEvents(runId: string | null): { view: RunView | null; stream: StreamState; invalidMessages: number } {
  const [held, dispatch] = useReducer(reducer, null);
  const [streamFor, setStreamFor] = useState<Keyed<StreamState> | null>(null);
  const [invalidFor, setInvalidFor] = useState<Keyed<number> | null>(null);

  useEffect(() => {
    if (!runId || !API_BASE) return;
    const source = new EventSource(`${API_BASE}/api/runs/${encodeURIComponent(runId)}/events`);

    const handle = (message: MessageEvent<string>) => {
      const envelope = parseEnvelope(message.data);
      if (!envelope) {
        setInvalidFor((prev) => ({ runId, value: prev && prev.runId === runId ? prev.value + 1 : 1 }));
        return;
      }
      dispatch(envelope);
      if (envelope.type === "run.outcome") {
        source.close();
        setStreamFor({ runId, value: "closed" });
      }
    };

    source.onopen = () => setStreamFor({ runId, value: "open" });
    source.onerror = () =>
      setStreamFor({ runId, value: source.readyState === EventSource.CLOSED ? "closed" : "reconnecting" });
    source.onmessage = handle;
    for (const type of KNOWN_EVENT_TYPES) source.addEventListener(type, handle as EventListener);

    return () => {
      for (const type of KNOWN_EVENT_TYPES) source.removeEventListener(type, handle as EventListener);
      source.close();
    };
  }, [runId]);

  if (!runId) return { view: null, stream: "idle", invalidMessages: 0 };

  const view = held && held.runId === runId ? held : initialRunView(runId);
  const stream: StreamState = !API_BASE
    ? "unavailable"
    : streamFor && streamFor.runId === runId
      ? streamFor.value
      : "connecting";
  const invalidMessages = invalidFor && invalidFor.runId === runId ? invalidFor.value : 0;

  return { view, stream, invalidMessages };
}
