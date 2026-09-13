import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// A controlled EventSource and fetch, so replay, live stream and run switching happen in a known order.

const BASE = "https://backend.test";
const RUN_A = "run-aaaa-0001";
const RUN_B = "run-bbbb-0002";
const PROOF = { chain_head: "a".repeat(64), signature: "b".repeat(128), public_key: "c".repeat(64) };

type Listener = (message: MessageEvent<string>) => void;

class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: Listener | null = null;
  listeners = new Map<string, Set<Listener>>();

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(listener);
  }

  removeEventListener(type: string, listener: Listener) {
    this.listeners.get(type)?.delete(listener);
  }

  close() {
    this.readyState = FakeEventSource.CLOSED;
  }

  open() {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.();
  }

  emit(type: string, data: unknown) {
    const message = { data: JSON.stringify(data) } as MessageEvent<string>;
    for (const listener of this.listeners.get(type) ?? []) listener(message);
  }

  giveUp() {
    this.readyState = FakeEventSource.CLOSED;
    this.onerror?.();
  }
}

const env = (runId: string, seq: number, type: string, payload: Record<string, unknown>) => ({ seq, run_id: runId, type, at: "t", payload });

/** Replay responses per run, served in request order. A run with nothing queued replays an empty history. */
let replays: Map<string, Array<() => Promise<unknown>>>;

/** A replay body that makes the fake backend answer 500. */
const REPLAY_FAILS = Symbol("replay fails");

function deferred() {
  let resolve: (value: unknown) => void = () => {};
  const promise = new Promise<unknown>((r) => (resolve = r));
  return { promise, resolve };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  replays = new Map();
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", BASE);
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const runId = decodeURIComponent(url.split("/api/runs/")[1].split("/")[0]);
      const next = replays.get(runId)?.shift();
      const body = next ? await next() : [];
      if (body === REPLAY_FAILS) return { ok: false, status: 500, json: async () => ({}) };
      return { ok: true, status: 200, json: async () => body };
    }),
  );
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

async function loadHook() {
  return (await import("@/lib/api/useRunEvents")).useRunEvents;
}

describe("useRunEvents", () => {
  it("ends the run when the replay already holds a valid signed outcome, and closes the stream", async () => {
    replays.set(RUN_A, [async () => [env(RUN_A, 1, "run.created", { request_text: "raise Pro" }), env(RUN_A, 2, "run.outcome", { outcome: "SUCCESS", ...PROOF })]]);
    const useRunEvents = await loadHook();
    const { result } = renderHook(() => useRunEvents(RUN_A));

    await waitFor(() => expect(result.current.stream).toBe("closed"));
    expect(result.current.view?.outcome?.outcome).toBe("SUCCESS");
    expect(FakeEventSource.instances[0].readyState).toBe(FakeEventSource.CLOSED);
  });

  it("does not end the run on an invalid outcome or a SUCCESS without its signed head", async () => {
    const useRunEvents = await loadHook();
    const { result } = renderHook(() => useRunEvents(RUN_A));
    const source = FakeEventSource.instances[0];

    act(() => source.open());
    act(() => source.emit("run.outcome", env(RUN_A, 1, "run.outcome", { outcome: "DONE" })));
    act(() => source.emit("run.outcome", env(RUN_A, 2, "run.outcome", { outcome: "SUCCESS" })));

    await waitFor(() =>
      expect(result.current.view?.rejected).toEqual([
        { seq: 1, type: "run.outcome" },
        { seq: 2, type: "run.outcome" },
      ]),
    );
    expect(result.current.stream).toBe("open");
    expect(result.current.view?.outcome).toBeNull();
    expect(source.readyState).toBe(FakeEventSource.OPEN);
  });

  it("reports a stream the browser gave up on as failed, not finished", async () => {
    const useRunEvents = await loadHook();
    const { result } = renderHook(() => useRunEvents(RUN_A));

    act(() => FakeEventSource.instances[0].giveUp());
    await waitFor(() => expect(result.current.stream).toBe("failed"));
  });

  it("merges a slow replay with a live event that arrived first, in sequence order", async () => {
    const first = deferred();
    replays.set(RUN_A, [() => first.promise]);
    const useRunEvents = await loadHook();
    const { result } = renderHook(() => useRunEvents(RUN_A));
    const source = FakeEventSource.instances[0];

    act(() => source.emit("ledger.completed", env(RUN_A, 2, "ledger.completed", { ledger_id: 7, entry_hash: "bb" })));
    await act(async () => first.resolve([env(RUN_A, 1, "ledger.pending", { ledger_id: 7, step_no: 1, app: "stripe" })]));

    await waitFor(() => expect(result.current.view?.ledger[0]?.state).toBe("completed"));
    expect(result.current.view?.unplaced).toEqual([]);
  });

  it("keeps the malformed count from the newest replay when an older replay finishes last", async () => {
    const initial = deferred();
    const reconcile = deferred();
    replays.set(RUN_A, [() => initial.promise, () => reconcile.promise]);
    const useRunEvents = await loadHook();
    const { result } = renderHook(() => useRunEvents(RUN_A));
    const source = FakeEventSource.instances[0];

    const outcome = env(RUN_A, 3, "run.outcome", { outcome: "SUCCESS", ...PROOF });
    act(() => source.emit("run.outcome", outcome));
    await act(async () => reconcile.resolve([outcome, { not: "an envelope" }]));
    await waitFor(() => expect(result.current.invalidMessages).toBe(1));

    await act(async () => initial.resolve([]));
    expect(result.current.invalidMessages).toBe(1);
    expect(result.current.stream).toBe("closed");
  });

  it("keeps an older replay's malformed count when the newer replay fails", async () => {
    const initial = deferred();
    replays.set(RUN_A, [() => initial.promise, async () => REPLAY_FAILS]);
    const useRunEvents = await loadHook();
    const { result } = renderHook(() => useRunEvents(RUN_A));
    const source = FakeEventSource.instances[0];

    const outcome = env(RUN_A, 3, "run.outcome", { outcome: "SUCCESS", ...PROOF });
    act(() => source.emit("run.outcome", outcome));
    await waitFor(() => expect(result.current.stream).toBe("closed"));

    await act(async () => initial.resolve([outcome, { not: "an envelope" }]));
    await waitFor(() => expect(result.current.invalidMessages).toBe(1));
  });

  it("never lets a queued event from the previous run change the new run", async () => {
    const useRunEvents = await loadHook();
    const { result, rerender } = renderHook(({ runId }) => useRunEvents(runId), { initialProps: { runId: RUN_A } });
    const oldSource = FakeEventSource.instances[0];
    const queued = [...oldSource.listeners.get("run.created")!][0];

    rerender({ runId: RUN_B });
    const newSource = FakeEventSource.instances[1];
    act(() => newSource.emit("run.created", env(RUN_B, 1, "run.created", { request_text: "new run" })));
    await waitFor(() => expect(result.current.view?.requestText).toBe("new run"));

    act(() => queued({ data: JSON.stringify(env(RUN_A, 5, "run.created", { request_text: "old run" })) } as MessageEvent<string>));
    expect(result.current.view?.runId).toBe(RUN_B);
    expect(result.current.view?.requestText).toBe("new run");
    expect(oldSource.readyState).toBe(FakeEventSource.CLOSED);
  });
});
