import { describe, expect, it } from "vitest";

import { initialMonitorView, parseMonitorEvent, reduceMonitor, summarizeMonitor, type MonitorEvent } from "@/lib/api/monitor";

const RUN = "3f7c1a52-0000-4000-8000-000000000001";
const json = (value: unknown) => JSON.stringify(value);

const detected = {
  plan_key: "pro",
  app: "notion",
  expected: { minor_units: 2500, currency: "usd" },
  observed: { minor_units: 2400, currency: "usd" },
  raw_value: "24",
  detected_at: "2026-09-13T20:10:00Z",
};

describe("parseMonitorEvent", () => {
  it("parses each event type, bare or inside an envelope", () => {
    expect(parseMonitorEvent("monitor.ok", json({ checked_at: "2026-09-13T20:00:00Z" }))).toEqual({ type: "monitor.ok", checkedAt: "2026-09-13T20:00:00Z" });
    expect(parseMonitorEvent("message", json({ type: "drift.detected", payload: detected }))).toMatchObject({
      type: "drift.detected",
      app: "notion",
      expected: { minorUnits: 2500, currency: "usd" },
      observed: { minorUnits: 2400, currency: "usd" },
    });
    expect(parseMonitorEvent("drift.healed", json({ plan_key: "pro", app: "notion", run_id: RUN }))).toEqual({
      type: "drift.healed",
      planKey: "pro",
      app: "notion",
      runId: RUN,
    });
  });

  it("accepts an unreadable observed price as null but rejects a malformed one", () => {
    expect(parseMonitorEvent("drift.detected", json({ ...detected, observed: null }))).toMatchObject({ observed: null });
    expect(parseMonitorEvent("drift.detected", json({ ...detected, observed: { minor_units: 24.5, currency: "usd" } }))).toBeNull();
  });

  it("rejects malformed events", () => {
    expect(parseMonitorEvent("monitor.ok", "not json")).toBeNull();
    expect(parseMonitorEvent("monitor.ok", json({ checked_at: "yesterday-ish" }))).toBeNull();
    expect(parseMonitorEvent("drift.detected", json({ ...detected, app: "slack" }))).toBeNull();
    expect(parseMonitorEvent("drift.detected", json({ ...detected, expected: { minor_units: 2500, currency: "USD" } }))).toBeNull();
    expect(parseMonitorEvent("drift.healed", json({ plan_key: "pro", app: "notion", run_id: "../etc" }))).toBeNull();
    expect(parseMonitorEvent("monitor.ok", json({ type: "drift.healed", checked_at: "2026-09-13T20:00:00Z" }))).toBeNull();
    expect(parseMonitorEvent("unknown.event", json({}))).toBeNull();
  });
});

describe("reduceMonitor and summarizeMonitor", () => {
  const drift = parseMonitorEvent("drift.detected", json(detected)) as MonitorEvent;
  const ok = parseMonitorEvent("monitor.ok", json({ checked_at: "2026-09-13T20:12:30Z" })) as MonitorEvent;
  const healed = parseMonitorEvent("drift.healed", json({ plan_key: "pro", app: "notion", run_id: RUN })) as MonitorEvent;

  it("never says there is no drift before the monitor reports a check", () => {
    const summary = summarizeMonitor(initialMonitorView, "open");
    expect(summary.tone).toBe("watching");
    expect(summary.text).not.toMatch(/no open drift/i);
  });

  it("shows an open drift in minor units until it is healed", () => {
    let view = reduceMonitor(initialMonitorView, ok);
    view = reduceMonitor(view, drift);
    const open = summarizeMonitor(view, "open");
    expect(open.tone).toBe("drift");
    expect(open.text).toContain("Notion shows 24.00 USD for pro, Stripe says 25.00 USD");

    view = reduceMonitor(view, healed);
    const after = summarizeMonitor(view, "open");
    expect(after.tone).toBe("clear");
    expect(after.text).toBe("Last check 20:12:30 UTC: no open drift.");
    expect(after.healed).toEqual({ app: "Notion", planKey: "pro", runId: RUN });
  });

  it("says when the stream is reconnecting", () => {
    expect(summarizeMonitor(reduceMonitor(initialMonitorView, ok), "reconnecting").text).toMatch(/^Drift monitor reconnecting\./);
  });
});
