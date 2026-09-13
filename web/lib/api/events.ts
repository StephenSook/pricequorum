/**
 * Run event stream: envelope parsing and the reducer that turns backend events into the
 * view the chapters render.
 *
 * Every field is read defensively from the envelope the backend actually sent. Nothing is
 * synthesised: a missing field stays null, and an event type this client does not know is
 * recorded in `unrecognized` so it shows up during integration instead of vanishing.
 * When `shared/openapi.json` lands, payload readers narrow to the generated types.
 */

export const OUTCOMES = ["SUCCESS", "PARTIAL", "REFUSED", "NEEDS_HUMAN"] as const;
export type Outcome = (typeof OUTCOMES)[number];

export const KNOWN_EVENT_TYPES = [
  "run.created",
  "run.status",
  "intent.parsed",
  "resolve.completed",
  "policy.decided",
  "approval.requested",
  "approval.decided",
  "ledger.pending",
  "adapter.fault",
  "readback.recovery",
  "ledger.completed",
  "subscription.migrated",
  "renewal.invoice",
  "readback.result",
  "invariant.result",
  "run.outcome",
] as const;
export type KnownEventType = (typeof KNOWN_EVENT_TYPES)[number];

export type Envelope = {
  seq: number;
  runId: string;
  type: string;
  at: string;
  payload: Record<string, unknown>;
};

export type ChapterId = "waiting" | "resolve" | "approve" | "migrate" | "verify" | "receipt";

export type LedgerStep = {
  ledgerId: number;
  stepNo: number | null;
  app: string | null;
  action: string | null;
  idempotencyKey: string | null;
  argsHash: string | null;
  state: "pending" | "completed";
  externalObjectId: string | null;
  prevHash: string | null;
  entryHash: string | null;
  fault: { callSite: string | null; kind: string | null; injected: boolean | null } | null;
  recovery: { foundLanded: boolean | null; externalObjectId: string | null } | null;
};

export type Readback = {
  app: string | null;
  minorUnits: number | null;
  currency: string | null;
  rawValue: string | null;
  readAt: string | null;
};

export type Invariant = { name: string | null; ok: boolean | null; detail: string | null; outcome: Outcome | null };

export type RunView = {
  runId: string;
  lastSeq: number;
  status: string | null;
  requestText: string | null;
  intent: { planHint: string | null; minorUnits: number | null; currency: string | null; interval: string | null } | null;
  resolution: {
    planKey: string | null;
    stripeProductId: string | null;
    stripePriceId: string | null;
    notionPageId: string | null;
    airtableRecordId: string | null;
    confidence: number | null;
    decidedBy: string | null;
  } | null;
  policy: { decision: string | null; rule: string | null; detail: string | null; remedy: string | null } | null;
  approval: {
    phase: "requested" | "decided";
    summary: string | null;
    argsHash: string | null;
    expiresAt: string | null;
    mode: string | null;
    decision: string | null;
    approverDisplay: string | null;
    decidedAt: string | null;
  } | null;
  ledger: LedgerStep[];
  readbacks: Readback[];
  invariants: Invariant[];
  outcome: {
    outcome: Outcome | null;
    remedy: string | null;
    chainHead: string | null;
    signature: string | null;
    publicKey: string | null;
  } | null;
  unrecognized: { seq: number; type: string }[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const str = (o: Record<string, unknown>, k: string): string | null => (typeof o[k] === "string" ? (o[k] as string) : null);
const num = (o: Record<string, unknown>, k: string): number | null =>
  typeof o[k] === "number" && Number.isFinite(o[k]) ? (o[k] as number) : null;
const bool = (o: Record<string, unknown>, k: string): boolean | null => (typeof o[k] === "boolean" ? (o[k] as boolean) : null);
const rec = (o: Record<string, unknown>, k: string): Record<string, unknown> => (isRecord(o[k]) ? (o[k] as Record<string, unknown>) : {});
const outcomeOf = (value: string | null): Outcome | null =>
  value !== null && (OUTCOMES as readonly string[]).includes(value) ? (value as Outcome) : null;

/** Parses one SSE `data:` payload. Returns null when the message is not a valid envelope. */
export function parseEnvelope(raw: string): Envelope | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(data)) return null;
  const seq = num(data, "seq");
  const runId = str(data, "run_id");
  const type = str(data, "type");
  if (seq === null || runId === null || type === null) return null;
  return { seq, runId, type, at: str(data, "at") ?? "", payload: rec(data, "payload") };
}

export function initialRunView(runId: string): RunView {
  return {
    runId,
    lastSeq: -1,
    status: null,
    requestText: null,
    intent: null,
    resolution: null,
    policy: null,
    approval: null,
    ledger: [],
    readbacks: [],
    invariants: [],
    outcome: null,
    unrecognized: [],
  };
}

function updateStep(ledger: LedgerStep[], ledgerId: number, patch: (step: LedgerStep) => LedgerStep): LedgerStep[] {
  return ledger.map((step) => (step.ledgerId === ledgerId ? patch(step) : step));
}

/** Applies one envelope. Replayed envelopes (seq already seen) are ignored, so reconnects are safe. */
export function reduceRun(view: RunView, event: Envelope): RunView {
  if (event.runId !== view.runId || event.seq <= view.lastSeq) return view;
  const p = event.payload;
  const next: RunView = { ...view, lastSeq: event.seq };

  switch (event.type) {
    case "run.created":
      return { ...next, requestText: str(p, "request_text") };
    case "run.status":
      return { ...next, status: str(p, "status") };
    case "intent.parsed": {
      const amount = rec(p, "new_amount");
      return {
        ...next,
        intent: {
          planHint: str(p, "plan_hint"),
          minorUnits: num(amount, "minor_units"),
          currency: str(amount, "currency"),
          interval: str(p, "interval"),
        },
      };
    }
    case "resolve.completed":
      return {
        ...next,
        resolution: {
          planKey: str(p, "plan_key"),
          stripeProductId: str(p, "stripe_product_id"),
          stripePriceId: str(p, "stripe_price_id"),
          notionPageId: str(p, "notion_page_id"),
          airtableRecordId: str(p, "airtable_record_id"),
          confidence: num(p, "confidence"),
          decidedBy: str(p, "decided_by"),
        },
      };
    case "policy.decided":
      return {
        ...next,
        policy: { decision: str(p, "decision"), rule: str(p, "rule"), detail: str(p, "detail"), remedy: str(p, "remedy") },
      };
    case "approval.requested":
      return {
        ...next,
        approval: {
          phase: "requested",
          summary: str(p, "summary"),
          argsHash: str(p, "args_hash"),
          expiresAt: str(p, "expires_at"),
          mode: str(p, "mode"),
          decision: "PENDING",
          approverDisplay: null,
          decidedAt: null,
        },
      };
    case "approval.decided":
      return {
        ...next,
        approval: {
          phase: "decided",
          summary: view.approval?.summary ?? null,
          argsHash: view.approval?.argsHash ?? null,
          expiresAt: view.approval?.expiresAt ?? null,
          mode: str(p, "mode") ?? view.approval?.mode ?? null,
          decision: str(p, "decision"),
          approverDisplay: str(p, "approver_display"),
          decidedAt: str(p, "decided_at"),
        },
      };
    case "ledger.pending": {
      const ledgerId = num(p, "ledger_id");
      if (ledgerId === null) return { ...next, unrecognized: [...view.unrecognized, { seq: event.seq, type: event.type }] };
      const step: LedgerStep = {
        ledgerId,
        stepNo: num(p, "step_no"),
        app: str(p, "app"),
        action: str(p, "action"),
        idempotencyKey: str(p, "idempotency_key"),
        argsHash: str(p, "args_hash"),
        state: "pending",
        externalObjectId: null,
        prevHash: null,
        entryHash: null,
        fault: null,
        recovery: null,
      };
      return { ...next, ledger: [...view.ledger.filter((s) => s.ledgerId !== ledgerId), step] };
    }
    case "adapter.fault": {
      const ledgerId = num(p, "ledger_id");
      if (ledgerId === null) return next;
      return {
        ...next,
        ledger: updateStep(view.ledger, ledgerId, (s) => ({
          ...s,
          fault: { callSite: str(p, "call_site"), kind: str(p, "kind"), injected: bool(p, "injected") },
        })),
      };
    }
    case "readback.recovery": {
      const ledgerId = num(p, "ledger_id");
      if (ledgerId === null) return next;
      return {
        ...next,
        ledger: updateStep(view.ledger, ledgerId, (s) => ({
          ...s,
          recovery: { foundLanded: bool(p, "found_landed"), externalObjectId: str(p, "external_object_id") },
        })),
      };
    }
    case "ledger.completed": {
      const ledgerId = num(p, "ledger_id");
      if (ledgerId === null) return next;
      return {
        ...next,
        ledger: updateStep(view.ledger, ledgerId, (s) => ({
          ...s,
          state: "completed",
          externalObjectId: str(p, "external_object_id"),
          prevHash: str(p, "prev_hash"),
          entryHash: str(p, "entry_hash"),
        })),
      };
    }
    case "readback.result": {
      const value = rec(p, "value");
      const readback: Readback = {
        app: str(p, "app"),
        minorUnits: num(value, "minor_units"),
        currency: str(value, "currency"),
        rawValue: str(p, "raw_value"),
        readAt: str(p, "read_at"),
      };
      return { ...next, readbacks: [...view.readbacks.filter((r) => r.app !== readback.app), readback] };
    }
    case "invariant.result":
      return {
        ...next,
        invariants: [
          ...view.invariants.filter((i) => i.name !== str(p, "name")),
          { name: str(p, "name"), ok: bool(p, "ok"), detail: str(p, "detail"), outcome: outcomeOf(str(p, "outcome")) },
        ],
      };
    case "run.outcome":
      return {
        ...next,
        outcome: {
          outcome: outcomeOf(str(p, "outcome")),
          remedy: str(p, "remedy"),
          chainHead: str(p, "chain_head"),
          signature: str(p, "signature"),
          publicKey: str(p, "public_key"),
        },
      };
    case "subscription.migrated":
    case "renewal.invoice":
      return next;
    default:
      return { ...next, unrecognized: [...view.unrecognized, { seq: event.seq, type: event.type }] };
  }
}

/** The chapter the UI should show, derived only from what the backend has reported so far. */
export function currentChapter(view: RunView): ChapterId {
  if (view.outcome) return "receipt";
  if (view.readbacks.length > 0 || view.invariants.length > 0) return "verify";
  if (view.ledger.length > 0) return "migrate";
  if (view.approval || view.policy) return "approve";
  if (view.resolution || view.intent) return "resolve";
  return "waiting";
}
