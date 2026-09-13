import { useEffect, useMemo, useState } from "react";
import EventSource from "react-native-sse";

import {
  KNOWN_EVENT_TYPES,
  envelopeFrom,
  foldEnvelopes,
  initialRunView,
  isTerminalOutcome,
  parseEnvelope,
  type Envelope,
  type KnownEventType,
  type RunView,
} from "../shared/api/events";
import { fetchJson } from "./client";

/**
 * - `retrying`: the stream has never opened and the app keeps trying.
 * - `reconnecting`: the stream was open and dropped.
 * - `closed`: the run reported a valid outcome.
 * - `failed`: the backend refused the stream (for example 404 or 500).
 */
export type StreamState = "idle" | "connecting" | "open" | "retrying" | "reconnecting" | "closed" | "failed" | "unavailable";

type Held = { key: string; bySeq: Map<number, Envelope> };
type Keyed<T> = { key: string; value: T };

const REPLAY_TIMEOUT_MS = 10_000;
const RECONNECT_MS = 3000;

/**
 * Follows one run with the same rules as web/lib/api/useRunEvents.ts.
 *
 * - On open it loads `GET /api/runs/{id}/events.json`, so a shared or reopened run shows
 *   everything already recorded.
 * - It subscribes to `GET /api/runs/{id}/events` for what happens next. Envelopes are kept by
 *   sequence number, so replayed or interleaved envelopes never duplicate a step. The library
 *   resends Last-Event-ID when it reconnects.
 * - The run ends only on a `run.outcome` with a valid outcome; then `events.json` is loaded
 *   again, which also carries event types the stream listeners cannot name.
 *
 * One difference from a browser EventSource: react-native-sse keeps polling after an HTTP
 * error, where a browser gives up. An error status of 400 or more therefore stops the stream
 * here and reads as failed.
 *
 * Every callback checks that its effect is still current, so an old run's queued event can
 * never touch a new run or a new backend address.
 */
export function useRunEvents(
  base: string,
  runId: string | null,
): { view: RunView | null; stream: StreamState; invalidMessages: number } {
  const [held, setHeld] = useState<Held | null>(null);
  const [streamFor, setStreamFor] = useState<Keyed<StreamState> | null>(null);
  const [streamInvalid, setStreamInvalid] = useState<Keyed<number> | null>(null);
  const [replayInvalid, setReplayInvalid] = useState<Keyed<number> | null>(null);
  const key = base && runId ? `${base}\n${runId}` : null;

  useEffect(() => {
    if (!base || !runId) return;
    const current = `${base}\n${runId}`;
    const runPath = `/api/runs/${encodeURIComponent(runId)}`;
    const source = new EventSource<KnownEventType>(`${base}${runPath}/events`, {
      pollingInterval: RECONNECT_MS,
      timeoutBeforeConnection: 0,
    });
    let cancelled = false;
    let opened = false;
    let finished = false;

    const stop = () => {
      source.removeAllEventListeners();
      source.close();
    };

    const replay = async () => {
      const result = await fetchJson(base, `${runPath}/events.json`, REPLAY_TIMEOUT_MS);
      if (cancelled) return;
      if (!result.ok) {
        console.warn(`[PriceQuorum] events.json for run ${runId}: ${result.detail}`);
        return;
      }
      const items: unknown[] = Array.isArray(result.body) ? result.body : [];
      const envelopes = items.map(envelopeFrom).filter((e): e is Envelope => e !== null && e.runId === runId);
      setReplayInvalid({ key: current, value: Array.isArray(result.body) ? items.length - envelopes.length : 1 });
      absorb(envelopes, true);
    };

    const finish = (reconcile: boolean) => {
      if (cancelled) return;
      finished = true;
      stop();
      setStreamFor({ key: current, value: "closed" });
      if (reconcile) void replay();
    };

    const absorb = (envelopes: Envelope[], fromReplay: boolean) => {
      if (cancelled || envelopes.length === 0) return;
      setHeld((prev) => {
        const bySeq = new Map(prev && prev.key === current ? prev.bySeq : undefined);
        for (const envelope of envelopes) if (!bySeq.has(envelope.seq)) bySeq.set(envelope.seq, envelope);
        return { key: current, bySeq };
      });
      if (!finished && envelopes.some(isTerminalOutcome)) finish(!fromReplay);
    };

    const handle = (event: { data: string | null }) => {
      if (cancelled) return;
      const envelope = event.data === null ? null : parseEnvelope(event.data);
      if (!envelope || envelope.runId !== runId) {
        setStreamInvalid((prev) => ({ key: current, value: prev && prev.key === current ? prev.value + 1 : 1 }));
        return;
      }
      absorb([envelope], false);
    };

    source.addEventListener("open", () => {
      if (cancelled || finished) return;
      opened = true;
      setStreamFor({ key: current, value: "open" });
    });
    source.addEventListener("error", (event) => {
      if (cancelled || finished) return;
      if (event.type === "error" && event.xhrStatus >= 400) {
        stop();
        setStreamFor({ key: current, value: "failed" });
        return;
      }
      setStreamFor({ key: current, value: opened ? "reconnecting" : "retrying" });
    });
    source.addEventListener("message", handle);
    for (const type of KNOWN_EVENT_TYPES) source.addEventListener(type, handle);
    void replay();

    return () => {
      cancelled = true;
      stop();
    };
  }, [base, runId]);

  const view = useMemo(() => {
    if (!runId) return null;
    return held && key && held.key === key ? foldEnvelopes(runId, held.bySeq.values()) : initialRunView(runId);
  }, [held, key, runId]);

  if (!runId) return { view: null, stream: "idle", invalidMessages: 0 };

  const stream: StreamState = !base ? "unavailable" : streamFor && streamFor.key === key ? streamFor.value : "connecting";
  const invalidMessages =
    (streamInvalid && streamInvalid.key === key ? streamInvalid.value : 0) +
    (replayInvalid && replayInvalid.key === key ? replayInvalid.value : 0);

  return { view, stream, invalidMessages };
}
