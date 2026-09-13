import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { View } from "react-native";

import { fetchJson } from "../../src/api/client";
import { useBackend } from "../../src/backend";
import { subtle } from "../../src/crypto";
import { parseLedgerExport, tamperCopy, verifyLedger, type ChainVerification, type LedgerExport } from "../../src/shared/verify/chain";
import { verdictOf, type VerdictTone } from "../../src/shared/verify/verdict";
import { Body, Button, Field, Hash, Loading, Notice, PaperCard, Screen, Title, Verdict, type Tone } from "../../src/ui/components";
import { colors, space } from "../../src/ui/theme";

type LoadState =
  | { kind: "loading" }
  | { kind: "unconfigured" }
  | { kind: "unreachable"; detail: string }
  | { kind: "invalid"; reasons: string[] }
  | { kind: "ready"; exported: LedgerExport; result: ChainVerification };

type Tampered = { entryId: number; field: string; result: ChainVerification } | null;

const TONE: Record<VerdictTone, Tone> = { trusted: "good", caution: "warn", failed: "bad" };

// verdictOf is shared with the web page, which says "in this browser"; on a phone the check runs here.
const onDevice = (text: string) => text.replace("in this browser", "on this phone");

const reasonOf = (err: unknown) => (err instanceof Error ? err.message : String(err));

export default function LedgerScreen() {
  const { base, loaded } = useBackend();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [tampered, setTampered] = useState<Tampered>(null);
  const [refreshing, setRefreshing] = useState(false);
  const generation = useRef(0);

  const load = useCallback(async () => {
    const mine = ++generation.current;
    const current = () => mine === generation.current;
    setTampered(null);
    if (!base) {
      setState({ kind: "unconfigured" });
      return;
    }
    setState({ kind: "loading" });
    const response = await fetchJson(base, "/api/ledger/export");
    if (!current()) return;
    if (!response.ok) {
      setState({ kind: "unreachable", detail: response.detail });
      return;
    }
    const parsed = parseLedgerExport(response.body);
    if (!parsed.ok) {
      setState({ kind: "invalid", reasons: parsed.reasons });
      return;
    }
    try {
      const result = await verifyLedger(parsed.value, subtle);
      if (current()) setState({ kind: "ready", exported: parsed.value, result });
    } catch (err) {
      if (current()) setState({ kind: "invalid", reasons: [`This phone could not run the check: ${reasonOf(err)}`] });
    }
  }, [base]);

  useFocusEffect(
    useCallback(() => {
      if (loaded) void load();
      return () => {
        generation.current += 1;
      };
    }, [loaded, load]),
  );

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const runTamper = async () => {
    if (state.kind !== "ready" || state.exported.rows.length === 0) return;
    const middle = state.exported.rows[Math.floor(state.exported.rows.length / 2)];
    const { copy, field } = tamperCopy(state.exported, middle.id);
    try {
      setTampered({ entryId: middle.id, field, result: await verifyLedger(copy, subtle) });
    } catch (err) {
      console.warn("[PriceQuorum] tamper check failed", err);
    }
  };

  return (
    <Screen refreshing={refreshing} onRefresh={refresh}>
      <PaperCard>
        <Title>Check the ledger yourself</Title>
        <Body soft>
          This screen downloads the ledger and recomputes every entry hash on this phone (SHA-256 over the RFC 8785
          canonical payload, chained from 32 zero bytes), then checks the Ed25519 signature on the head. The verdict
          reported by the server is not used.
        </Body>

        {!loaded || state.kind === "loading" ? <Loading label="Downloading the ledger export." /> : null}
        {loaded && state.kind === "unconfigured" ? (
          <Notice tone="warn" title="The app does not know where the backend runs, so there is no ledger to check yet.">
            Add the backend address in Settings.
          </Notice>
        ) : null}
        {state.kind === "unreachable" ? <Notice tone="warn" title={`${state.detail} Pull down to try again.`} /> : null}
        {state.kind === "invalid" ? (
          <Notice tone="bad" title="The export cannot be verified:">
            <View style={{ gap: space.xs }}>
              {state.reasons.map((reason) => (
                <Body key={reason}>{reason}</Body>
              ))}
            </View>
          </Notice>
        ) : null}

        {state.kind === "ready" ? (
          <View style={{ gap: space.md }}>
            {(() => {
              const verdict = verdictOf(state.result, state.exported.head);
              return <Verdict tone={TONE[verdict.tone]}>{onDevice(verdict.text)}</Verdict>;
            })()}
            <Field label="Entries">{String(state.result.entries)}</Field>
            <Field label="Recomputed head">
              <Hash value={state.result.computedHead} label="recomputed head" />
            </Field>
            <Field label="Published head">
              <Hash value={state.exported.head} label="published head" />
            </Field>
            <Field label="Public key">
              <Hash value={state.exported.publicKey} label="ledger public key" />
            </Field>
            <Field label="Signature">
              {state.result.signatureValid === null
                ? "not published"
                : state.result.signatureValid
                  ? "valid for this head and key"
                  : "does not verify"}
            </Field>
            <Body soft>
              The public key arrives in the same export as the ledger. A valid signature shows the export is consistent with
              that key; it does not by itself show who holds the key.
            </Body>
            {state.result.problems.map((problem) => (
              <Body key={problem} style={{ color: colors.refused }}>
                {problem}
              </Body>
            ))}

            <View style={{ gap: space.sm, borderTopWidth: 1, borderTopColor: "rgba(30,42,26,0.15)", paddingTop: space.md }}>
              <Body strong>Try to cheat</Body>
              <Body soft>
                Change one character inside one entry of a copy held on this phone, then verify that copy. The ledger on
                the server is not touched.
              </Body>
              <Button label="Edit one entry and re-verify" onPress={runTamper} disabled={state.exported.rows.length === 0} />
              {tampered ? (
                <View style={{ gap: space.sm }}>
                  <Body>
                    Changed field {tampered.field} in entry {tampered.entryId}.
                  </Body>
                  {(() => {
                    const verdict = verdictOf(tampered.result, state.exported.head);
                    return (
                      <Verdict tone={TONE[verdict.tone]} announce={false}>
                        {`Edited copy: ${onDevice(verdict.text)}`}
                      </Verdict>
                    );
                  })()}
                  <Button label="Discard the edited copy" onPress={() => setTampered(null)} secondary />
                </View>
              ) : null}
            </View>
          </View>
        ) : null}
      </PaperCard>
    </Screen>
  );
}
