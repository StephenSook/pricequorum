/**
 * Parser, reducer and summary for the drift monitor stream (docs/contracts/api.md:
 * GET /api/monitor/events). Events are validated before they reach the strip, and the strip never
 * says there is no drift until the monitor itself has reported a completed check.
 */
import { formatMinor } from "@/lib/format";

export const MONITOR_EVENT_TYPES = ["monitor.ok", "drift.detected", "drift.healed"] as const;

export type DriftApp = "stripe" | "notion" | "airtable";
export type MonitorMoney = { minorUnits: number; currency: string };

export type MonitorOk = { type: "monitor.ok"; checkedAt: string };
export type DriftDetected = {
  type: "drift.detected";
  planKey: string;
  app: DriftApp;
  expected: MonitorMoney;
  observed: MonitorMoney | null;
  rawValue: string | null;
  detectedAt: string;
};
export type DriftHealed = { type: "drift.healed"; planKey: string; app: DriftApp; runId: string };
export type MonitorEvent = MonitorOk | DriftDetected | DriftHealed;

const RUN_ID = /^[A-Za-z0-9-]{8,64}$/;
const APP_NAMES: Record<DriftApp, string> = { stripe: "Stripe", notion: "Notion", airtable: "Airtable" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const text = (o: Record<string, unknown>, k: string): string | null =>
  typeof o[k] === "string" && (o[k] as string).trim() !== "" ? (o[k] as string) : null;
const time = (o: Record<string, unknown>, k: string): string | null => {
  const value = text(o, k);
  return value !== null && !Number.isNaN(Date.parse(value)) ? value : null;
};
const appOf = (o: Record<string, unknown>): DriftApp | null => {
  const value = o.app;
  return value === "stripe" || value === "notion" || value === "airtable" ? value : null;
};

function money(value: unknown): MonitorMoney | null {
  if (!isRecord(value)) return null;
  const minor = value.minor_units;
  const currency = value.currency;
  return typeof minor === "number" && Number.isSafeInteger(minor) && typeof currency === "string" && /^[a-z]{3}$/.test(currency)
    ? { minorUnits: minor, currency }
    : null;
}

/**
 * Parses one message. `eventName` is the SSE event name the listener was registered for, or
 * "message" for unnamed events. The payload may arrive bare or inside a `{ type, payload }` envelope.
 */
export function parseMonitorEvent(eventName: string, raw: string): MonitorEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(data)) return null;
  const payload = isRecord(data.payload) ? data.payload : data;
  const declared = typeof data.type === "string" ? data.type : null;
  const type = eventName === "message" ? declared : eventName;
  if (declared !== null && type !== declared) return null;

  switch (type) {
    case "monitor.ok": {
      const checkedAt = time(payload, "checked_at");
      return checkedAt ? { type: "monitor.ok", checkedAt } : null;
    }
    case "drift.detected": {
      const planKey = text(payload, "plan_key");
      const app = appOf(payload);
      const expected = money(payload.expected);
      const detectedAt = time(payload, "detected_at");
      const observedPresent = payload.observed !== null && payload.observed !== undefined;
      const observed = money(payload.observed);
      if (!planKey || !app || !expected || !detectedAt || (observedPresent && observed === null)) return null;
      return {
        type: "drift.detected",
        planKey,
        app,
        expected,
        observed,
        rawValue: typeof payload.raw_value === "string" ? payload.raw_value : null,
        detectedAt,
      };
    }
    case "drift.healed": {
      const planKey = text(payload, "plan_key");
      const app = appOf(payload);
      const runId = text(payload, "run_id");
      if (!planKey || !app || !runId || !RUN_ID.test(runId)) return null;
      return { type: "drift.healed", planKey, app, runId };
    }
    default:
      return null;
  }
}

export type MonitorView = { lastCheckedAt: string | null; drifts: DriftDetected[]; healed: DriftHealed[] };

export const initialMonitorView: MonitorView = { lastCheckedAt: null, drifts: [], healed: [] };

const keyOf = (event: { planKey: string; app: DriftApp }) => `${event.planKey}:${event.app}`;

export function reduceMonitor(view: MonitorView, event: MonitorEvent): MonitorView {
  switch (event.type) {
    case "monitor.ok":
      return { ...view, lastCheckedAt: event.checkedAt };
    case "drift.detected":
      return { ...view, drifts: [...view.drifts.filter((d) => keyOf(d) !== keyOf(event)), event] };
    case "drift.healed":
      return {
        ...view,
        drifts: view.drifts.filter((d) => keyOf(d) !== keyOf(event)),
        healed: [event, ...view.healed.filter((h) => h.runId !== event.runId)].slice(0, 3),
      };
  }
}

export type MonitorConnection = "open" | "reconnecting" | "closed";

export type MonitorSummary = {
  tone: "watching" | "clear" | "drift";
  text: string;
  healed: { app: string; planKey: string; runId: string } | null;
};

const clock = (iso: string) => `${new Date(iso).toISOString().slice(11, 19)} UTC`;

export function summarizeMonitor(view: MonitorView, connection: MonitorConnection): MonitorSummary {
  const prefix =
    connection === "reconnecting" ? "Drift monitor reconnecting. " : connection === "closed" ? "Drift monitor stopped; reload to reconnect. " : "";
  const latestHealed = view.healed[0];
  const healed = latestHealed ? { app: APP_NAMES[latestHealed.app], planKey: latestHealed.planKey, runId: latestHealed.runId } : null;

  const drift = view.drifts[view.drifts.length - 1];
  if (drift) {
    const seen = drift.observed ? `shows ${formatMinor(drift.observed.minorUnits, drift.observed.currency)}` : "has no readable price";
    const others = view.drifts.length - 1;
    const more = others > 0 ? ` ${others} more drift${others === 1 ? "" : "s"} open.` : "";
    return {
      tone: "drift",
      text: `${prefix}Drift: ${APP_NAMES[drift.app]} ${seen} for ${drift.planKey}, Stripe says ${formatMinor(drift.expected.minorUnits, drift.expected.currency)}. Detected ${clock(drift.detectedAt)}.${more}`,
      healed,
    };
  }
  if (view.lastCheckedAt === null) {
    return { tone: "watching", text: `${prefix}Drift monitor connected. Waiting for its first check.`, healed };
  }
  return { tone: "clear", text: `${prefix}Last check ${clock(view.lastCheckedAt)}: no open drift.`, healed };
}
