import Constants from "expo-constants";
import { useEffect, useRef, useState } from "react";
import { StyleSheet, Text, TextInput, View } from "react-native";

import { checkHealth, type HealthCheck } from "../../src/api/client";
import { normalizeBase, useBackend } from "../../src/backend";
import { Body, Button, Field, healthSummary, Mono, Notice, PaperCard, Screen, StatusPill, Title } from "../../src/ui/components";
import { colors, fonts, space, TOUCH } from "../../src/ui/theme";

const SOURCE_TEXT = {
  settings: "Using the address saved on this phone.",
  build: "Using the address this build was made with.",
  none: "No backend address yet.",
} as const;

export default function SettingsScreen() {
  const { base, source, buildBase, loaded, save, reset } = useBackend();
  const [draft, setDraft] = useState("");
  const [health, setHealth] = useState<HealthCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const seeded = useRef(false);

  useEffect(() => {
    if (!loaded || seeded.current) return;
    seeded.current = true;
    setDraft(base);
  }, [loaded, base]);

  const check = async (address: string) => {
    setChecking(true);
    setHealth(null);
    const result = await checkHealth(address, 8000);
    setHealth(result);
    setChecking(false);
  };

  const saveAndCheck = async () => {
    setMessage(null);
    const normalized = normalizeBase(draft);
    if (normalized === null) {
      setMessage("Enter an address that starts with https:// or http://.");
      return;
    }
    try {
      await save(draft);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "The address could not be saved.");
      return;
    }
    setDraft(normalized);
    if (normalized) await check(normalized);
    else setHealth({ state: "unconfigured" });
  };

  const useBuildAddress = async () => {
    setMessage(null);
    await reset();
    setDraft(buildBase);
    if (buildBase) await check(buildBase);
    else setHealth({ state: "unconfigured" });
  };

  const summary = checking ? { tone: "neutral" as const, label: "Checking the backend", detail: null } : health ? healthSummary(health) : null;
  const version = Constants.expoConfig?.version ?? "unknown";

  return (
    <Screen>
      <PaperCard>
        <Title>Settings</Title>
        <Body soft>
          The app reads runs, the ledger and the evidence from the PriceQuorum backend at this address. It never holds
          Stripe, Notion, Airtable or Slack credentials, and approvals happen in Slack.
        </Body>

        <Text nativeID="backend-label" style={styles.label}>
          Backend address
        </Text>
        <TextInput
          accessibilityLabel="Backend address"
          accessibilityLabelledBy="backend-label"
          value={draft}
          onChangeText={setDraft}
          placeholder="https://your-backend.example.com"
          placeholderTextColor={colors.inkSoft}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          textContentType="URL"
          returnKeyType="done"
          onSubmitEditing={saveAndCheck}
          editable={loaded && !checking}
          style={styles.input}
        />
        <Body soft>{loaded ? SOURCE_TEXT[source] : "Reading the saved address."}</Body>
        {message ? <Notice tone="bad" title={message} /> : null}

        <Button label={checking ? "Checking" : "Save and check"} onPress={saveAndCheck} disabled={!loaded || checking} />
        {source === "settings" ? (
          <Button
            label={buildBase ? "Use the address this build was made with" : "Clear the saved address"}
            onPress={useBuildAddress}
            disabled={checking}
            secondary
          />
        ) : null}
      </PaperCard>

      {summary ? (
        <View style={{ gap: space.sm }}>
          <StatusPill tone={summary.tone} label={summary.label} detail={summary.detail} />
          {health?.state === "degraded" ? (
            <PaperCard>
              <Body strong>The backend answered, but reports a problem:</Body>
              {health.problems.map((problem) => (
                <Body key={problem}>{problem}</Body>
              ))}
            </PaperCard>
          ) : null}
        </View>
      ) : null}

      <PaperCard>
        <Field label="App version">{version}</Field>
        <Field label="Build address">{buildBase ? <Mono>{buildBase}</Mono> : "none"}</Field>
      </PaperCard>
    </Screen>
  );
}

const styles = StyleSheet.create({
  label: { fontFamily: fonts.semibold, fontSize: 14, color: colors.inkSoft },
  input: {
    minHeight: TOUCH,
    borderRadius: 8,
    borderWidth: 1.5,
    borderColor: colors.inkSoft,
    backgroundColor: colors.paperLight,
    color: colors.ink,
    fontFamily: fonts.mono,
    fontSize: 16,
    paddingHorizontal: space.md,
    paddingVertical: space.md,
  },
});
