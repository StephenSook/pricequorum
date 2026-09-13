import { router } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Animated, Easing, Linking, StyleSheet, Text, View } from "react-native";

import { agreementOf, type LedgerStep, type Outcome, type Readback, type RunView } from "../shared/api/events";
import { formatMinor } from "../shared/format";
import { Body, Button, ChapterCard, Field, Hash, Mono, Notice, TONE_COLOR, Verdict, type Tone } from "../ui/components";
import { colors, fonts, space } from "../ui/theme";

const DECIDED_BY: Record<string, string> = {
  exact_id: "matched on the shared pq_plan_id",
  fuzzy: "matched by name similarity",
  human: "confirmed by a person",
};

export function Resolve({ view }: { view: RunView }) {
  const { intent, resolution, policy } = view;
  const ids = [
    { app: "Stripe", label: "Product", value: resolution?.stripeProductId ?? null },
    { app: "Stripe", label: "Current price", value: resolution?.stripePriceId ?? null },
    { app: "Notion", label: "Pricing page", value: resolution?.notionPageId ?? null },
    { app: "Airtable", label: "Catalogue record", value: resolution?.airtableRecordId ?? null },
  ];
  const needsHuman = policy?.decision === "NEEDS_HUMAN" && !resolution;

  return (
    <ChapterCard index={1} title="Find the plan in all three apps">
      <Field label="Request">{view.requestText ?? "not reported"}</Field>
      <Field label="Understood as">
        {intent && intent.minorUnits !== null && intent.currency
          ? `${intent.planHint ?? "plan"} to ${formatMinor(intent.minorUnits, intent.currency)}${intent.interval ? ` per ${intent.interval}` : ""}`
          : "waiting for the parsed intent"}
      </Field>
      {ids.map((id) => (
        <Field key={id.label} label={`${id.app} ${id.label.toLowerCase()}`}>
          <Hash value={id.value} label={`${id.app} ${id.label}`} />
        </Field>
      ))}
      {resolution ? (
        <View style={chapter.row}>
          <Text style={chapter.bigNumber}>{resolution.confidence ?? "?"}</Text>
          <Body soft style={{ flex: 1 }}>
            confidence, {resolution.decidedBy ? (DECIDED_BY[resolution.decidedBy] ?? resolution.decidedBy) : "method not reported"}
          </Body>
        </View>
      ) : null}
      {needsHuman ? (
        <Notice tone="warn" title="Stopped: the plan could not be matched with confidence.">
          {policy?.remedy ?? undefined}
        </Notice>
      ) : null}
    </ChapterCard>
  );
}

const DECIDED_MODE: Record<string, string> = {
  slack: "Decided in Slack",
  operator: "Decided with the operator fallback, not Slack",
  sandbox_auto: "Sandbox auto-approver for the public demo, not a person",
};

const WAITING_MODE: Record<string, string> = {
  slack: "Waiting for a decision in Slack",
  operator: "Waiting for the operator fallback, not Slack",
  sandbox_auto: "Waiting for the sandbox auto-approver, not a person",
};

const DECISION_COLOR: Record<string, string> = {
  APPROVED: colors.success,
  DENIED: colors.refused,
  EXPIRED: colors.needsHuman,
  PENDING: colors.inkSoft,
};

function useRemaining(expiresAt: string | null, active: boolean): string | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active || !expiresAt) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active, expiresAt]);
  if (!expiresAt) return null;
  const end = Date.parse(expiresAt);
  if (Number.isNaN(end)) return null;
  const seconds = Math.max(0, Math.round((end - now) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function Approve({ view }: { view: RunView }) {
  const { approval, policy } = view;
  const pending = approval?.phase === "requested";
  const remaining = useRemaining(approval?.expiresAt ?? null, pending);
  const [slackMissing, setSlackMissing] = useState(false);
  const decision = approval?.decision ?? null;
  const modeText = approval?.mode ? ((pending ? WAITING_MODE : DECIDED_MODE)[approval.mode] ?? approval.mode) : "approval channel not reported";
  const decidedInSlack = !approval?.mode || approval.mode === "slack";

  const openSlack = () => {
    Linking.openURL("slack://open").catch((err) => {
      console.warn("[PriceQuorum] could not open Slack", err);
      setSlackMissing(true);
    });
  };

  return (
    <ChapterCard index={2} title="Ask a person first">
      {policy ? (
        <Field label="Policy check">
          <Body strong>{policy.decision ?? "not reported"}</Body>
          {policy.rule ? <Mono style={{ color: colors.inkSoft }}>{policy.rule}</Mono> : null}
          {policy.detail ? <Body>{policy.detail}</Body> : null}
        </Field>
      ) : null}

      {approval ? (
        <View style={chapter.slackCard}>
          <View style={chapter.row}>
            <View style={chapter.badge}>
              <Text style={chapter.badgeText}>PQ</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Body strong>PriceQuorum</Body>
              <Body soft>{modeText}</Body>
            </View>
          </View>
          <Body>{approval.summary ?? "Summary not reported"}</Body>
          <View style={[chapter.row, { flexWrap: "wrap" }]}>
            <Text
              style={[chapter.stamp, { color: DECISION_COLOR[decision ?? "PENDING"] ?? colors.inkSoft, borderColor: DECISION_COLOR[decision ?? "PENDING"] ?? colors.inkSoft }]}
            >
              {decision ? decision.toLowerCase() : pending ? "waiting" : "not reported"}
            </Text>
            {pending && remaining ? <Body soft>expires in {remaining}</Body> : null}
            {approval.approverDisplay ? <Body soft>by {approval.approverDisplay}</Body> : null}
          </View>
          {pending && decidedInSlack ? (
            <View style={{ gap: space.sm }}>
              <Body soft>Approve or deny in Slack. This app never approves a change itself.</Body>
              <Button label="Open Slack" onPress={openSlack} hint="Opens the Slack app, where the approval request waits" />
              {slackMissing ? <Notice tone="warn" title="Slack could not be opened on this phone." /> : null}
            </View>
          ) : null}
        </View>
      ) : policy?.decision === "REFUSED" ? (
        <Notice tone="bad" title="Refused before asking anyone.">
          {policy.remedy ?? undefined}
        </Notice>
      ) : (
        <Body soft>No approval requested yet.</Body>
      )}
    </ChapterCard>
  );
}

const FAULT_TEXT: Record<string, string> = {
  timeout: "The call timed out after the request was sent",
  rate_limit: "Rate limited by the app",
  conflict_409: "Another request held the same idempotency key",
  server_5xx: "The app returned a server error",
};

function StepRow({ step }: { step: LedgerStep }) {
  return (
    <View style={chapter.step}>
      <View style={chapter.row}>
        <Mono style={{ color: colors.inkSoft }}>{step.stepNo ?? "?"}</Mono>
        <Body strong style={{ textTransform: "capitalize" }}>
          {step.app ?? "unknown app"}
        </Body>
        <Text style={[chapter.stepState, { color: step.state === "completed" ? colors.success : colors.needsHuman }]}>
          {step.state === "completed" ? "written" : "pending"}
        </Text>
      </View>
      <Body>{step.action?.replaceAll("_", " ") ?? "action not reported"}</Body>
      <Mono style={{ color: colors.inkSoft, fontSize: 12 }}>{step.idempotencyKey ?? "no idempotency key reported"}</Mono>

      {step.fault ? (
        <View style={chapter.fault} accessibilityLiveRegion="polite">
          <Body strong style={{ color: colors.refused }}>
            {step.fault.kind ? (FAULT_TEXT[step.fault.kind] ?? step.fault.kind) : "Fault reported"}
            {step.fault.injected === true
              ? " (injected on purpose for this run)"
              : step.fault.injected === null
                ? " (the backend did not say whether this fault was injected)"
                : ""}
          </Body>
          <Body soft={!step.recovery}>
            {step.recovery
              ? step.recovery.foundLanded === true
                ? "Read the app back: the write had landed, so it was not sent again."
                : step.recovery.foundLanded === false
                  ? "Read the app back: the write had not landed, so it was retried with the same key."
                  : "Read the app back, but the backend did not report whether the write had landed."
              : "Reading the app back to learn whether the write landed."}
          </Body>
        </View>
      ) : null}

      {step.entryHash ? (
        <View style={chapter.row}>
          <Body soft>ledger entry</Body>
          <Hash value={step.entryHash} label={`ledger entry ${step.stepNo ?? ""}`} />
        </View>
      ) : null}
    </View>
  );
}

export function Migrate({ view }: { view: RunView }) {
  const steps = [...view.ledger].sort((a, b) => (a.stepNo ?? a.ledgerId) - (b.stepNo ?? b.ledgerId));
  const written = steps.filter((s) => s.state === "completed").length;
  const invoice = view.renewalInvoice;

  const counts = new Map<string, number>();
  for (const move of view.subscriptions) {
    if (move.subscriptionId) counts.set(move.subscriptionId, (counts.get(move.subscriptionId) ?? 0) + 1);
  }
  const repeated = [...counts].filter(([, n]) => n > 1).map(([id]) => id);

  return (
    <ChapterCard index={3} title="Write each change exactly once">
      <View style={chapter.row}>
        <Text style={chapter.bigNumber}>
          {written}/{steps.length}
        </Text>
        <Body soft style={{ flex: 1 }}>
          steps written. Each row is recorded as pending before the app is called.
        </Body>
      </View>
      {steps.map((step) => (
        <StepRow key={step.ledgerId} step={step} />
      ))}

      {view.subscriptions.length > 0 || invoice ? (
        <View style={chapter.subscribers}>
          <Body strong>Existing subscribers</Body>
          {repeated.length > 0 ? (
            <Notice
              tone="bad"
              title={
                repeated.length === 1
                  ? `Subscription ${repeated[0]} was migrated more than once.`
                  : `${repeated.length} subscriptions were migrated more than once.`
              }
            />
          ) : null}
          {view.subscriptions.map((move) => (
            <Body key={move.seq}>
              <Text style={chapter.monoInline}>{move.subscriptionId ?? "subscription id not reported"}</Text>
              {" moved from "}
              <Text style={chapter.monoInline}>{move.fromPrice ?? "price not reported"}</Text>
              {" to "}
              <Text style={chapter.monoInline}>{move.toPrice ?? "price not reported"}</Text>
              {move.prorationBehavior ? `, proration: ${move.prorationBehavior}` : ""}
            </Body>
          ))}
          {invoice ? (
            <Body>
              {"Renewal invoice "}
              <Text style={chapter.monoInline}>{invoice.invoiceId ?? "id not reported"}</Text>
              {invoice.minorUnits !== null && invoice.currency ? ` billed ${formatMinor(invoice.minorUnits, invoice.currency)}` : ", amount not reported"}
              {invoice.testClockId ? " on a Stripe test clock" : ""}.
            </Body>
          ) : null}
        </View>
      ) : null}
    </ChapterCard>
  );
}

const APPS = [
  { key: "stripe", name: "Stripe", role: "billing" },
  { key: "notion", name: "Notion", role: "pricing page" },
  { key: "airtable", name: "Airtable", role: "catalogue" },
] as const;

type PricedReadback = Readback & { minorUnits: number; currency: string };
const priced = (r: Readback | undefined): r is PricedReadback => r !== undefined && r.minorUnits !== null && r.currency !== null;

export function Verify({ view }: { view: RunView }) {
  // The same agreement the web page uses, in RECONCILED_APPS order (stripe, notion, airtable).
  const { readbacks: values, allReported, allPriced, agree, failing, invariantsOk, value, proven } = agreementOf(view);

  let tone: Tone = "neutral";
  let message = "Waiting for every app to be read back.";
  if (proven && value) {
    tone = "good";
    message = `All three agree: ${formatMinor(value.minorUnits, value.currency)}, read back fresh from each app.`;
  } else if (agree && invariantsOk) {
    tone = "bad";
    message = "The values agree, but not every app reported a fresh read, so this run cannot be called a success.";
  } else if (allReported && !allPriced) {
    tone = "bad";
    message = "At least one app was read but returned no price. This run cannot be called a success.";
  } else if (allPriced && !agree) {
    tone = "bad";
    message = "The apps disagree. This run cannot be called a success.";
  } else if (failing.length > 0) {
    tone = "bad";
    message = `${failing.length} check${failing.length === 1 ? "" : "s"} failed or reported no result.`;
  } else if (agree) {
    message = "The three values agree. Waiting for the invariant checks.";
  }

  return (
    <ChapterCard index={4} title="Read all three back">
      {APPS.map((app, i) => {
        const r = values[i];
        return (
          <View key={app.key} style={chapter.readback}>
            <Body strong>
              {app.name} <Text style={{ fontFamily: fonts.body, color: colors.inkSoft }}>{app.role}</Text>
            </Body>
            <Text style={chapter.amount}>{priced(r) ? formatMinor(r.minorUnits, r.currency) : r ? "no price found" : "not read yet"}</Text>
            {r?.rawValue ? <Mono style={{ color: colors.inkSoft, fontSize: 12 }}>stored as {r.rawValue}</Mono> : null}
          </View>
        );
      })}
      <Verdict tone={tone}>{message}</Verdict>
      {view.invariants.map((inv, index) => (
        <View key={`${inv.name ?? "unnamed"}-${index}`} style={[chapter.row, { flexWrap: "wrap" }]}>
          <Text style={{ fontFamily: fonts.semibold, color: inv.ok === true ? colors.success : colors.refused }}>
            {inv.ok === true ? "passed" : inv.ok === false ? "failed" : "no result"}
          </Text>
          <Mono>{inv.name ?? "unnamed check"}</Mono>
          {inv.detail ? <Body soft>{inv.detail}</Body> : null}
        </View>
      ))}
    </ChapterCard>
  );
}

const STAMP: Record<Outcome, { label: string; color: string; meaning: string }> = {
  SUCCESS: { label: "Verified", color: colors.success, meaning: "Every app was read back and agrees." },
  PARTIAL: { label: "Partial", color: colors.refused, meaning: "Some writes landed and some did not. The ledger names which." },
  REFUSED: { label: "Refused", color: colors.refused, meaning: "A rule blocked this change." },
  NEEDS_HUMAN: { label: "Needs a person", color: colors.needsHuman, meaning: "PriceQuorum would not guess." },
};

const UNPROVEN_SUCCESS = {
  label: "Success reported",
  color: colors.needsHuman,
  meaning:
    "The backend reported success, but this page did not receive fresh read-backs from all three apps that agree with every check passing.",
};

export function Receipt({ view }: { view: RunView }) {
  const outcome = view.outcome;
  const progress = useRef(new Animated.Value(1)).current;

  // The one loud moment of a run: the outcome stamp lands. Skipped when Reduce Motion is on.
  useEffect(() => {
    if (!outcome) return;
    let cancelled = false;
    AccessibilityInfo.isReduceMotionEnabled()
      .then((reduce) => {
        if (cancelled || reduce) return;
        progress.setValue(0);
        Animated.timing(progress, {
          toValue: 1,
          duration: 450,
          delay: 350,
          easing: Easing.in(Easing.poly(4)),
          useNativeDriver: true,
        }).start();
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [outcome?.outcome, progress]);

  if (!outcome) return null;
  // A reported SUCCESS earns the Verified stamp only when this screen itself saw the proof.
  const stamp = outcome.outcome === "SUCCESS" && !agreementOf(view).proven ? UNPROVEN_SUCCESS : STAMP[outcome.outcome];
  const scale = progress.interpolate({ inputRange: [0, 1], outputRange: [1.8, 1] });
  const rotate = progress.interpolate({ inputRange: [0, 1], outputRange: ["-14deg", "-6deg"] });

  return (
    <ChapterCard index={5} title="The receipt">
      <Animated.View
        accessibilityRole="text"
        accessibilityLabel={`Outcome: ${stamp.label}`}
        style={[chapter.outcomeStamp, { borderColor: stamp.color, opacity: progress, transform: [{ scale }, { rotate }] }]}
      >
        <Text style={[chapter.outcomeText, { color: stamp.color }]}>{stamp.label}</Text>
      </Animated.View>
      <Body strong>{stamp.meaning}</Body>
      {outcome.remedy ? (
        <Body>
          <Text style={{ color: colors.inkSoft }}>What would allow it: </Text>
          {outcome.remedy}
        </Body>
      ) : null}
      <Field label="Ledger head">
        <Hash value={outcome.chainHead} label="ledger head hash" />
      </Field>
      <Field label="Signature">
        <Hash value={outcome.signature} label="Ed25519 signature" />
      </Field>
      <Field label="Public key">
        <Hash value={outcome.publicKey} label="ledger public key" />
      </Field>
      <Button label="Check the ledger on this phone" onPress={() => router.push("/ledger")} secondary />
    </ChapterCard>
  );
}

export const TONE_FOR_STREAM = TONE_COLOR;

const chapter = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: space.sm },
  bigNumber: { fontFamily: fonts.display, fontSize: 32, color: colors.olive },
  slackCard: { backgroundColor: "rgba(255,255,255,0.85)", borderRadius: 8, padding: space.lg, gap: space.md, borderWidth: 1, borderColor: "rgba(30,42,26,0.15)" },
  badge: { width: 40, height: 40, borderRadius: 6, backgroundColor: colors.olive, alignItems: "center", justifyContent: "center" },
  badgeText: { fontFamily: fonts.display, color: colors.paperLight, fontSize: 15 },
  stamp: {
    fontFamily: fonts.display,
    fontSize: 16,
    textTransform: "uppercase",
    borderWidth: 3,
    borderRadius: 4,
    paddingHorizontal: space.md,
    paddingVertical: space.xs,
    transform: [{ rotate: "-4deg" }],
  },
  step: { borderTopWidth: 1, borderTopColor: "rgba(70,80,22,0.2)", paddingTop: space.md, gap: space.xs },
  stepState: { marginLeft: "auto", fontFamily: fonts.semibold, fontSize: 15 },
  fault: { backgroundColor: "rgba(163,38,42,0.08)", borderRadius: 6, padding: space.md, gap: space.xs },
  subscribers: { borderTopWidth: 1, borderTopColor: "rgba(30,42,26,0.15)", paddingTop: space.md, gap: space.sm },
  monoInline: { fontFamily: fonts.mono, fontSize: 13 },
  readback: { borderWidth: 1, borderColor: "rgba(30,42,26,0.15)", backgroundColor: "rgba(246,240,225,0.8)", borderRadius: 8, padding: space.md, gap: 2 },
  amount: { fontFamily: fonts.display, fontSize: 24, color: colors.ink },
  outcomeStamp: { alignSelf: "center", borderWidth: 5, borderRadius: 8, paddingHorizontal: space.xl, paddingVertical: space.md, marginVertical: space.md },
  outcomeText: { fontFamily: fonts.display, fontSize: 32, textTransform: "uppercase" },
});
