import { router, useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { fetchJson } from "../../src/api/client";
import { useBackend } from "../../src/backend";
import { OUTCOMES } from "../../src/shared/api/events";
import { parseEvalReport, parseProof, type EvalReport, type Proof } from "../../src/shared/api/proof";
import { Body, Loading, Mono, Notice, PaperCard, Screen, Title } from "../../src/ui/components";
import { colors, fonts, space, TOUCH } from "../../src/ui/theme";

type State =
  | { kind: "loading" }
  | { kind: "unconfigured" }
  | { kind: "unreachable"; detail: string }
  | { kind: "invalid"; reasons: string[] }
  | { kind: "ready"; proof: Proof; report: EvalReport | null; reportProblem: string | null };

const percent = (p: number) => `${Math.round(p * 1000) / 10}%`;

function ledgerValue(ledger: Proof["ledger"]): string {
  if (!ledger || ledger.chainIntact === null) return "not reported";
  if (!ledger.chainIntact) return "broken";
  if (ledger.signatureValid === false) return "signature invalid";
  if (ledger.signatureValid === true) return "intact, signed";
  return "intact, unsigned";
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Body soft>{label}</Body>
    </View>
  );
}

function NamedFailures({ proof }: { proof: Proof }) {
  const failed = proof.scenarios.total - proof.scenarios.passed;
  const named = proof.namedFailures;
  const s = (n: number) => (n === 1 ? "" : "s");

  if (named && named.length > 0) {
    return (
      <View style={{ gap: space.sm }}>
        {named.map((f, index) => (
          <View key={`${f.scenarioId}-${index}`} style={styles.failure}>
            <Mono style={{ fontFamily: fonts.mono }}>{f.scenarioId}</Mono>
            <Body soft>{f.explanation}</Body>
          </View>
        ))}
        {named.length < failed ? (
          <Body strong style={{ color: colors.needsHuman }}>
            {failed - named.length} more failed scenario{s(failed - named.length)} {failed - named.length === 1 ? "was" : "were"} not named.
          </Body>
        ) : null}
      </View>
    );
  }
  if (failed > 0) {
    return (
      <Body strong style={{ color: colors.needsHuman }}>
        {failed} scenario{s(failed)} failed, but the backend {named === null ? "sent no list of named failures" : "named none of them"}.
      </Body>
    );
  }
  return (
    <Body soft>
      {named === null ? "Every scenario passed. The backend sent no list of named failures." : "The backend reported no failed scenarios."}
    </Body>
  );
}

export default function EvidenceScreen() {
  const { base, loaded } = useBackend();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const generation = useRef(0);

  const load = useCallback(async () => {
    const mine = ++generation.current;
    if (!base) {
      setState({ kind: "unconfigured" });
      return;
    }
    setState({ kind: "loading" });
    const [proofRes, reportRes] = await Promise.all([fetchJson(base, "/api/proof"), fetchJson(base, "/api/evals/latest")]);
    if (mine !== generation.current) return;
    if (!proofRes.ok) {
      setState({ kind: "unreachable", detail: proofRes.detail });
      return;
    }
    const proof = parseProof(proofRes.body);
    if (!proof.ok) {
      setState({ kind: "invalid", reasons: proof.reasons });
      return;
    }
    let report: EvalReport | null = null;
    let reportProblem: string | null = null;
    if (!reportRes.ok) reportProblem = reportRes.detail;
    else {
      const parsed = parseEvalReport(reportRes.body);
      if (parsed.ok) report = parsed.value;
      else reportProblem = parsed.reasons.join(" ");
    }
    setState({ kind: "ready", proof: proof.value, report, reportProblem });
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

  return (
    <Screen refreshing={refreshing} onRefresh={refresh}>
      <PaperCard>
        <Title>The evidence</Title>
        <Body soft>
          The headline numbers are recomputed by the backend from its own database each time this screen loads. The
          per-scenario list is the latest stored evaluation report. Failed scenarios are listed with their explanation
          rather than hidden.
        </Body>

        {!loaded || state.kind === "loading" ? <Loading label="Loading the latest results." /> : null}
        {loaded && state.kind === "unconfigured" ? (
          <Notice tone="warn" title="The app does not know where the backend runs, so there are no results to show yet.">
            Add the backend address in Settings.
          </Notice>
        ) : null}
        {state.kind === "unreachable" ? <Notice tone="warn" title={`${state.detail} Pull down to try again.`} /> : null}
        {state.kind === "invalid" ? (
          <Notice tone="bad" title="The proof response could not be used:">
            <View style={{ gap: space.xs }}>
              {state.reasons.map((reason) => (
                <Body key={reason}>{reason}</Body>
              ))}
            </View>
          </Notice>
        ) : null}

        {state.kind === "ready" ? (
          <View style={{ gap: space.lg }}>
            <View>
              <Text style={styles.headline}>
                {state.proof.scenarios.passed} of {state.proof.scenarios.total}
              </Text>
              <Body>
                evaluation scenarios passed
                {state.proof.scenarios.wilson95
                  ? `, 95% interval ${percent(state.proof.scenarios.wilson95[0])} to ${percent(state.proof.scenarios.wilson95[1])}`
                  : ""}
                {state.proof.scenarios.runsPerScenario ? `, ${state.proof.scenarios.runsPerScenario} runs each` : ""}.
              </Body>
            </View>

            <Stat
              value={state.proof.duplicateWritesPrevented === null ? "not reported" : String(state.proof.duplicateWritesPrevented)}
              label="duplicate writes prevented across forced retries"
            />
            <Stat
              value={
                state.proof.forbiddenRefused
                  ? `${state.proof.forbiddenRefused.refused} of ${state.proof.forbiddenRefused.attempted}`
                  : "not reported"
              }
              label="forbidden actions refused"
            />
            <Stat
              value={ledgerValue(state.proof.ledger)}
              label={`ledger chain${state.proof.ledger?.entries != null ? `, ${state.proof.ledger.entries} entries` : ""}`}
            />

            {state.proof.outcomes ? (
              <View style={{ gap: space.sm }}>
                <Body strong>Outcomes across all scenario runs</Body>
                <View style={styles.chips}>
                  {OUTCOMES.map((o) => (
                    <View key={o} style={styles.chip}>
                      <Mono>{o}</Mono>
                      <Body> {state.proof.outcomes![o]}</Body>
                    </View>
                  ))}
                </View>
              </View>
            ) : null}

            <View style={{ gap: space.sm }}>
              <Body strong>Named failures</Body>
              <NamedFailures proof={state.proof} />
            </View>

            <View style={{ gap: space.sm }}>
              <Body strong>Every scenario</Body>
              {state.report ? (
                state.report.results.map((r, index) => (
                  <View key={`${r.scenarioId}-${index}`} style={styles.result}>
                    <View style={styles.resultHead}>
                      <Mono style={{ flex: 1 }}>{r.scenarioId}</Mono>
                      <Text style={{ fontFamily: fonts.semibold, color: r.passed ? colors.success : colors.refused }}>
                        {r.passed ? "passed" : "failed"}
                      </Text>
                    </View>
                    <Body soft>
                      expected {r.expectedOutcome ?? "not reported"}, observed {r.observedOutcome ?? "not reported"}
                    </Body>
                    {r.runId ? (
                      <Pressable
                        accessibilityRole="link"
                        accessibilityLabel={`Open the receipt for ${r.scenarioId}`}
                        onPress={() => router.push(`/runs/${encodeURIComponent(r.runId!)}`)}
                        style={styles.link}
                      >
                        <Text style={styles.linkText}>receipt</Text>
                      </Pressable>
                    ) : null}
                  </View>
                ))
              ) : (
                <Body style={{ color: colors.needsHuman }}>{state.reportProblem ?? "The per-scenario report is not available."}</Body>
              )}
            </View>

            {state.proof.generatedAt || state.proof.commitSha ? (
              <Body soft>
                Computed {state.proof.generatedAt ?? "at an unreported time"}
                {state.proof.commitSha ? ` for commit ${state.proof.commitSha}` : ""}.
              </Body>
            ) : null}
          </View>
        ) : null}
      </PaperCard>
    </Screen>
  );
}

const styles = StyleSheet.create({
  headline: { fontFamily: fonts.display, fontSize: 48, lineHeight: 52, color: colors.ink },
  stat: { borderWidth: 1, borderColor: "rgba(30,42,26,0.15)", backgroundColor: "rgba(246,240,225,0.7)", borderRadius: 8, padding: space.md },
  statValue: { fontFamily: fonts.display, fontSize: 26, color: colors.ink },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  chip: { flexDirection: "row", alignItems: "center", borderWidth: 1, borderColor: "rgba(30,42,26,0.2)", borderRadius: 999, paddingHorizontal: space.md, paddingVertical: space.xs },
  failure: { borderLeftWidth: 4, borderLeftColor: colors.refused, backgroundColor: "rgba(246,240,225,0.7)", borderRadius: 6, padding: space.md, gap: 2 },
  result: { borderBottomWidth: 1, borderBottomColor: "rgba(30,42,26,0.1)", paddingVertical: space.sm, gap: 2 },
  resultHead: { flexDirection: "row", alignItems: "center", gap: space.sm },
  link: { minHeight: TOUCH, justifyContent: "center", alignSelf: "flex-start" },
  linkText: { fontFamily: fonts.semibold, color: colors.olive, textDecorationLine: "underline" },
});
