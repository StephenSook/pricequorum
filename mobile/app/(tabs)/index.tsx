import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Animated, StyleSheet, Text, TextInput, View } from "react-native";

import { ApiError, checkHealth, createRun, type HealthCheck } from "../../src/api/client";
import { useBackend } from "../../src/backend";
import { Body, Button, healthSummary, Notice, Screen, StatusPill } from "../../src/ui/components";
import { colors, fonts, space, TOUCH } from "../../src/ui/theme";

const APPS = ["Stripe", "Notion", "Airtable", "Slack"] as const;

type RunError = { message: string; remedy: string | null };

export default function HomeScreen() {
  const { base, loaded, source } = useBackend();
  const [request, setRequest] = useState("Raise Pro to $25 per month");
  const [health, setHealth] = useState<HealthCheck | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<RunError | null>(null);
  const drop = useRef(new Animated.Value(1)).current;

  // The ticket drops into place once, unless Reduce Motion is on.
  useEffect(() => {
    let cancelled = false;
    AccessibilityInfo.isReduceMotionEnabled()
      .then((reduce) => {
        if (cancelled || reduce) return;
        drop.setValue(0);
        Animated.spring(drop, { toValue: 1, useNativeDriver: true, friction: 7, tension: 40 }).start();
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [drop]);

  useFocusEffect(
    useCallback(() => {
      if (!loaded) return;
      let cancelled = false;
      setHealth(null);
      checkHealth(base).then((result) => {
        if (!cancelled) setHealth(result);
      });
      return () => {
        cancelled = true;
      };
    }, [base, loaded]),
  );

  const start = async () => {
    const text = request.trim();
    if (!text || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createRun(base, text);
      router.push(`/runs/${encodeURIComponent(created.runId)}`);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? { message: err.message, remedy: err.remedy }
          : { message: "The request could not be sent.", remedy: "Check your connection and try again." },
      );
    } finally {
      setSubmitting(false);
    }
  };

  const pill = loaded ? healthSummary(health) : healthSummary(null);
  const translateY = drop.interpolate({ inputRange: [0, 1], outputRange: [-60, 0] });
  const rotate = drop.interpolate({ inputRange: [0, 1], outputRange: ["-4deg", "0deg"] });

  return (
    <Screen>
      <StatusPill tone={pill.tone} label={pill.label} detail={pill.detail} />

      <Animated.View style={[styles.ticket, { opacity: drop, transform: [{ translateY }, { rotate }] }]}>
        <View style={styles.ticketBody}>
          <Text style={styles.kicker}>one price</Text>
          <Text accessibilityRole="header" maxFontSizeMultiplier={1.3} style={[styles.display, { transform: [{ rotate: "-2deg" }] }]}>
            Three
          </Text>
          <Text maxFontSizeMultiplier={1.3} style={[styles.display, { alignSelf: "flex-end" }]}>
            systems
          </Text>
          <Text style={styles.kicker}>agree</Text>
          <Body light style={styles.lede}>
            Ask for a price change in plain words. PriceQuorum waits for approval in Slack, changes Stripe, Notion and
            Airtable exactly once, then reads all three back before it calls the job done.
          </Body>

          <Text nativeID="request-label" style={styles.label}>
            Price change
          </Text>
          <TextInput
            accessibilityLabel="Price change"
            accessibilityLabelledBy="request-label"
            value={request}
            onChangeText={setRequest}
            maxLength={500}
            editable={!submitting}
            autoCorrect={false}
            autoCapitalize="sentences"
            returnKeyType="go"
            onSubmitEditing={start}
            placeholder="Raise Pro to $25 per month"
            placeholderTextColor="rgba(239,230,210,0.5)"
            style={[styles.input, submitting && { opacity: 0.6 }]}
          />
        </View>
        <View accessibilityLabel="Connected apps" style={styles.stub}>
          {APPS.map((app) => (
            <Text key={app} style={styles.app}>
              {app}
            </Text>
          ))}
        </View>
      </Animated.View>

      <Button
        label={submitting ? "Starting the run" : "Start the run"}
        onPress={start}
        disabled={submitting || !loaded || !request.trim()}
        hint="Sends the request to the backend, which asks for approval in Slack before any write"
      />

      {error ? (
        <Notice tone="bad" title={error.message}>
          {error.remedy ?? undefined}
        </Notice>
      ) : null}

      {loaded && source === "none" ? (
        <Notice tone="warn" title="This app does not know where the backend runs yet.">
          <Body>Add its address in Settings. Nothing on this phone is shown until the backend answers.</Body>
          <View style={{ marginTop: space.sm }}>
            <Button label="Open Settings" onPress={() => router.push("/settings")} secondary />
          </View>
        </Notice>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  ticket: { borderRadius: 14, overflow: "hidden", backgroundColor: colors.olive },
  ticketBody: { paddingHorizontal: space.xl, paddingTop: space.xxl, paddingBottom: space.xl, gap: space.xs },
  kicker: {
    fontFamily: fonts.semibold,
    fontSize: 13,
    letterSpacing: 2,
    textTransform: "uppercase",
    color: colors.paperDeep,
    textAlign: "center",
  },
  display: {
    fontFamily: fonts.display,
    fontSize: 52,
    lineHeight: 56,
    color: colors.paperLight,
    textTransform: "uppercase",
    textShadowColor: "rgba(35,40,11,0.8)",
    textShadowOffset: { width: 3, height: 3 },
    textShadowRadius: 0,
  },
  lede: { textAlign: "center", marginTop: space.md, color: colors.paper },
  label: { fontFamily: fonts.semibold, fontSize: 14, color: colors.paperDeep, marginTop: space.lg },
  input: {
    minHeight: TOUCH,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "rgba(239,230,210,0.3)",
    backgroundColor: "rgba(35,40,11,0.6)",
    color: colors.paperLight,
    fontFamily: fonts.body,
    fontSize: 18,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
  },
  stub: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "center",
    gap: space.lg,
    borderTopWidth: 2,
    borderStyle: "dashed",
    borderTopColor: "rgba(239,230,210,0.3)",
    paddingVertical: space.md,
    paddingHorizontal: space.lg,
  },
  app: { fontFamily: fonts.semibold, fontSize: 14, color: colors.paperDeep },
});
