"use client";

import { useEffect, useMemo, useState } from "react";

import { API_BASE } from "@/lib/api/client";
import {
  KNOWN_EVENT_TYPES,
  envelopeFrom,
  foldEnvelopes,
  initialRunView,
  parseEnvelope,
  type Envelope,
  type RunView,
} from "@/lib/api/events";

/**
 * - `retrying`: the stream has never opened and the browser keeps trying.
 * - `reconnecting`: the stream was open and dropped.
 * - `closed`: the run reported its outcome.
 * - `failed`: the browser gave up (for example the backend answered 404 or 500).
 */
export type StreamState = "idle" | "connecting" | "open" | "retrying" | "reconnecting" | "closed" | "failed" | "unavailable";

type Held = { runId: string; bySeq: Map<number, Envelope> };
type Keyed<T> = { runId: string; value: T };

const REPLAY_TIMEOUT_MS = 10_000;

/**
 * Follows one run.
 *
 * - When a run page opens it loads `GET /api/runs/{id}/events.json`, so a refreshed or shared
 *   link shows everything already recorded. A first EventSource connection sends no
 *   Last-Event-ID, so the stream alone cannot be relied on for history.
 * - It subscribes to `GET /api/runs/{id}/events` for what happens next. Envelopes are kept by
 *   sequence number, so replayed or interleaved envelopes never duplicate a step.
 * - When the run ends it loads `events.json` again, which also carries event types the stream
 *   listeners cannot name.
 *
 * State only changes inside callbacks; everything returned is derived from `runId`, so
 * switching runs never shows the previous run's events or stream status.
 */
export function useRunEvents(runId: string | null): { view: RunView | null; stream: StreamState; invalidMessages: number } {
  const [held, setHeld] = useState<Held | null>(null);
  const [streamFor, setStreamFor] = useState<Keyed<StreamState> | null>(null);
  const [streamInvalid, setStreamInvalid] = useState<Keyed<number> | null>(null);
  const [replayInvalid, setReplayInvalid] = useState<Keyed<number> | null>(null);

  useEffect(() => {
    if (!runId || !API_BASE) return;
    const base = `${API_BASE}/api/runs/${encodeURIComponent(runId)}`;
    const source = new EventSource(`${base}/events`);
    let cancelled = false;
    let opened = false;
    let finished = false;

    const finish = (reconcile: boolean) => {
      finished = true;
      source.close();
      setStreamFor({ runId, value: "closed" });
      if (reconcile) void replay();
    };

    const absorb = (envelopes: Envelope[], fromReplay: boolean) => {
      if (envelopes.length === 0) return;
      setHeld((prev) => {
        const bySeq = new Map(prev && prev.runId === runId ? prev.bySeq : undefined);
        for (const envelope of envelopes) if (!bySeq.has(envelope.seq)) bySeq.set(envelope.seq, envelope);
        return { runId, bySeq };
      });
      if (!finished && envelopes.some((e) => e.type === "run.outcome")) finish(!fromReplay);
    };

    const replay = async () => {
      let body: unknown;
      try {
        const res = await fetch(`${base}/events.json`, { cache: "no-store", signal: AbortSignal.timeout(REPLAY_TIMEOUT_MS) });
        if (!res.ok) {
          console.warn(`[PriceQuorum] events.json for run ${runId} answered with status ${res.status}`);
          return;
        }
        body = await res.json();
      } catch (err) {
        console.warn(`[PriceQuorum] events.json for run ${runId} could not be loaded`, err);
        return;
      }
      if (cancelled) return;
      const items: unknown[] = Array.isArray(body) ? body : [];
      const envelopes = items.map(envelopeFrom).filter((e): e is Envelope => e !== null && e.runId === runId);
      setReplayInvalid({ runId, value: Array.isArray(body) ? items.length - envelopes.length : 1 });
      absorb(envelopes, true);
    };

    const handle = (message: MessageEvent<string>) => {
      const envelope = parseEnvelope(message.data);
      if (!envelope || envelope.runId !== runId) {
        setStreamInvalid((prev) => ({ runId, value: prev && prev.runId === runId ? prev.value + 1 : 1 }));
        return;
      }
      absorb([envelope], false);
    };

    source.onopen = () => {
      opened = true;
      setStreamFor({ runId, value: "open" });
    };
    source.onerror = () => {
      if (finished) return;
      const value: StreamState = source.readyState === EventSource.CLOSED ? "failed" : opened ? "reconnecting" : "retrying";
      setStreamFor({ runId, value });
    };
    source.onmessage = handle;
    for (const type of KNOWN_EVENT_TYPES) source.addEventListener(type, handle as EventListener);
    void replay();

    return () => {
      cancelled = true;
      for (const type of KNOWN_EVENT_TYPES) source.removeEventListener(type, handle as EventListener);
      source.close();
    };
  }, [runId]);

  const view = useMemo(() => {
    if (!runId) return null;
    return held && held.runId === runId ? foldEnvelopes(runId, held.bySeq.values()) : initialRunView(runId);
  }, [held, runId]);

  if (!runId) return { view: null, stream: "idle", invalidMessages: 0 };

  const stream: StreamState = !API_BASE
    ? "unavailable"
    : streamFor && streamFor.runId === runId
      ? streamFor.value
      : "connecting";
  const invalidMessages =
    (streamInvalid && streamInvalid.runId === runId ? streamInvalid.value : 0) +
    (replayInvalid && replayInvalid.runId === runId ? replayInvalid.value : 0);

  return { view, stream, invalidMessages };
}
