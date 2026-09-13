import { describe, expect, it } from "vitest";

import {
  currentChapter,
  envelopeFrom,
  foldEnvelopes,
  initialRunView,
  isTerminalOutcome,
  parseEnvelope,
  reduceRun,
  type Envelope,
} from "@/lib/api/events";

const RUN = "3f7c1a52-0000-4000-8000-000000000001";

function envelope(seq: number, type: string, payload: Record<string, unknown>): Envelope {
  return { seq, runId: RUN, type, at: "2026-09-13T20:00:00Z", payload };
}

function apply(...events: Envelope[]) {
  return events.reduce(reduceRun, initialRunView(RUN));
}

describe("parseEnvelope", () => {
  it("accepts a well-formed envelope", () => {
    const parsed = parseEnvelope(
      JSON.stringify({ seq: 3, run_id: RUN, type: "run.created", at: "t", payload: { request_text: "raise Pro" } }),
    );
    expect(parsed).toEqual({ seq: 3, runId: RUN, type: "run.created", at: "t", payload: { request_text: "raise Pro" } });
  });

  it("rejects invalid JSON and envelopes missing seq, run_id, type or an object payload", () => {
    expect(parseEnvelope("not json")).toBeNull();
    expect(parseEnvelope(JSON.stringify({ run_id: RUN, type: "x", payload: {} }))).toBeNull();
    expect(parseEnvelope(JSON.stringify({ seq: 1, type: "x", payload: {} }))).toBeNull();
    expect(parseEnvelope(JSON.stringify({ seq: 1, run_id: RUN, payload: {} }))).toBeNull();
    expect(parseEnvelope(JSON.stringify({ seq: 1, run_id: RUN, type: "run.outcome" }))).toBeNull();
    expect(parseEnvelope(JSON.stringify({ seq: 1, run_id: RUN, type: "run.outcome", payload: "SUCCESS" }))).toBeNull();
  });

  it("rejects a fractional sequence number and accepts decoded objects from events.json", () => {
    expect(envelopeFrom({ seq: 1.5, run_id: RUN, type: "run.created", payload: {} })).toBeNull();
    expect(envelopeFrom({ seq: 2, run_id: RUN, type: "run.created", payload: {} })).toMatchObject({ seq: 2, payload: {} });
  });
});

describe("isTerminalOutcome", () => {
  it("is true only for a run.outcome carrying one of the four outcomes", () => {
    expect(isTerminalOutcome(envelope(1, "run.outcome", { outcome: "SUCCESS" }))).toBe(true);
    expect(isTerminalOutcome(envelope(1, "run.outcome", { outcome: "DONE" }))).toBe(false);
    expect(isTerminalOutcome(envelope(1, "run.outcome", {}))).toBe(false);
    expect(isTerminalOutcome(envelope(1, "run.status", { outcome: "SUCCESS" }))).toBe(false);
  });
});

describe("reduceRun", () => {
  it("ignores replayed sequence numbers so a reconnect cannot duplicate a ledger step", () => {
    const pending = envelope(5, "ledger.pending", { ledger_id: 11, step_no: 1, app: "stripe", action: "create_price" });
    const view = apply(pending, pending, envelope(4, "ledger.pending", { ledger_id: 12 }));
    expect(view.ledger).toHaveLength(1);
    expect(view.lastSeq).toBe(5);
  });

  it("ignores events for a different run", () => {
    const foreign: Envelope = { ...envelope(1, "run.created", { request_text: "x" }), runId: "other" };
    expect(apply(foreign).requestText).toBeNull();
  });

  it("attaches a fault and its read-back recovery to the same ledger step, then completes it", () => {
    const view = apply(
      envelope(1, "ledger.pending", { ledger_id: 7, step_no: 1, app: "stripe", action: "create_price", idempotency_key: "pq:pro:v2:create_price" }),
      envelope(2, "adapter.fault", { ledger_id: 7, call_site: "stripe.price.create", kind: "timeout", injected: true }),
      envelope(3, "readback.recovery", { ledger_id: 7, call_site: "stripe.price.create", found_landed: true, external_object_id: "price_new" }),
      envelope(4, "ledger.completed", { ledger_id: 7, external_object_id: "price_new", prev_hash: "aa", entry_hash: "bb" }),
    );
    const [step] = view.ledger;
    expect(step.fault).toEqual({ callSite: "stripe.price.create", kind: "timeout", injected: true });
    expect(step.recovery).toEqual({ foundLanded: true, externalObjectId: "price_new" });
    expect(step.state).toBe("completed");
    expect(step.entryHash).toBe("bb");
    expect(view.unplaced).toEqual([]);
    expect(currentChapter(view)).toBe("migrate");
  });

  it("keeps a ledger event that names no known step visible instead of dropping it", () => {
    const view = apply(
      envelope(1, "ledger.completed", { ledger_id: 99, entry_hash: "bb" }),
      envelope(2, "adapter.fault", { call_site: "stripe.price.create", kind: "timeout" }),
    );
    expect(view.ledger).toHaveLength(0);
    expect(view.unplaced).toEqual([
      { seq: 1, type: "ledger.completed" },
      { seq: 2, type: "adapter.fault" },
    ]);
  });

  it("keeps money as integer minor units, never invents a missing amount, and records freshness", () => {
    const view = apply(
      envelope(1, "readback.result", { app: "notion", value: { minor_units: 2500, currency: "usd" }, raw_value: "24.999999999999996", fresh: true }),
      envelope(2, "readback.result", { app: "airtable", value: null, raw_value: null }),
    );
    expect(view.readbacks.find((r) => r.app === "notion")).toMatchObject({ minorUnits: 2500, currency: "usd", rawValue: "24.999999999999996", fresh: true });
    expect(view.readbacks.find((r) => r.app === "airtable")).toMatchObject({ minorUnits: null, currency: null, fresh: null });
  });

  it("reads an amount that is not whole minor units with a currency code as missing", () => {
    const view = apply(
      envelope(1, "readback.result", { app: "stripe", value: { minor_units: 24.5, currency: "usd" }, fresh: true }),
      envelope(2, "readback.result", { app: "notion", value: { minor_units: 2450, currency: "US dollars" }, fresh: true }),
    );
    expect(view.readbacks.map((r) => [r.minorUnits, r.currency])).toEqual([
      [null, null],
      [null, null],
    ]);
  });

  it("does not let an unnamed invariant replace another result", () => {
    const view = apply(
      envelope(1, "invariant.result", { ok: false, detail: "first" }),
      envelope(2, "invariant.result", { ok: true, detail: "second" }),
      envelope(3, "invariant.result", { name: "prices_agree", ok: false }),
      envelope(4, "invariant.result", { name: "prices_agree", ok: true }),
    );
    expect(view.invariants.map((i) => [i.name, i.ok])).toEqual([
      [null, false],
      [null, true],
      ["prices_agree", true],
    ]);
  });

  it("keeps every migration of the same subscription so a duplicate write stays visible", () => {
    const move = { subscription_id: "sub_1", from_price: "price_old", to_price: "price_new", proration_behavior: "none" };
    const view = apply(
      envelope(1, "subscription.migrated", move),
      envelope(2, "subscription.migrated", move),
      envelope(3, "renewal.invoice", { invoice_id: "in_1", amount: { minor_units: 2500, currency: "usd" }, test_clock_id: "clock_1" }),
    );
    expect(view.subscriptions.map((s) => [s.seq, s.subscriptionId])).toEqual([
      [1, "sub_1"],
      [2, "sub_1"],
    ]);
    expect(view.renewalInvoice).toEqual({ invoiceId: "in_1", minorUnits: 2500, currency: "usd", testClockId: "clock_1" });
    expect(currentChapter(view)).toBe("migrate");
  });

  it("records unknown event types instead of dropping them", () => {
    const view = apply(envelope(9, "brand.new.event", {}));
    expect(view.unrecognized).toEqual([{ seq: 9, type: "brand.new.event" }]);
  });

  it("rejects an outcome outside the four classes instead of showing a receipt", () => {
    const view = apply(envelope(1, "run.outcome", { outcome: "DONE", chain_head: "cc" }));
    expect(view.outcome).toBeNull();
    expect(view.rejected).toEqual([{ seq: 1, type: "run.outcome" }]);
    expect(currentChapter(view)).toBe("waiting");
  });

  it("walks chapters in order as real events arrive", () => {
    let view = initialRunView(RUN);
    expect(currentChapter(view)).toBe("waiting");
    view = reduceRun(view, envelope(1, "resolve.completed", { plan_key: "pro", confidence: 100, decided_by: "exact_id" }));
    expect(currentChapter(view)).toBe("resolve");
    view = reduceRun(view, envelope(2, "approval.requested", { summary: "Pro 20 to 25", mode: "slack" }));
    expect(currentChapter(view)).toBe("approve");
    view = reduceRun(view, envelope(3, "approval.decided", { decision: "APPROVED", approver_display: "Stephen" }));
    expect(view.approval).toMatchObject({ phase: "decided", decision: "APPROVED", summary: "Pro 20 to 25", mode: "slack" });
    view = reduceRun(view, envelope(4, "run.outcome", { outcome: "SUCCESS", chain_head: "cc" }));
    expect(view.outcome).toMatchObject({ outcome: "SUCCESS", chainHead: "cc" });
    expect(currentChapter(view)).toBe("receipt");
  });
});

describe("foldEnvelopes", () => {
  it("builds the same view whatever order the replay and the stream deliver, counting a repeat once", () => {
    const events = [
      envelope(1, "ledger.pending", { ledger_id: 7, step_no: 1, app: "stripe" }),
      envelope(2, "ledger.completed", { ledger_id: 7, entry_hash: "bb" }),
      envelope(3, "run.outcome", { outcome: "SUCCESS" }),
    ];
    const inOrder = foldEnvelopes(RUN, events);
    const interleaved = foldEnvelopes(RUN, [events[2], events[1], events[1], events[0], { ...events[0], runId: "other" }]);
    expect(interleaved).toEqual(inOrder);
    expect(interleaved.ledger[0].state).toBe("completed");
    expect(interleaved.unplaced).toEqual([]);
  });
});
