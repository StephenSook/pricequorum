import * as Clipboard from "expo-clipboard";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ActivityIndicator,
  ImageBackground,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from "react-native";
import { SafeAreaView, type Edge } from "react-native-safe-area-context";

import type { HealthCheck } from "../shared/api/health";
import { truncateHash } from "../shared/format";
import { colors, fonts, space, TOUCH } from "./theme";

const paperTexture = require("../../assets/paper-grain.webp");

export type Tone = "good" | "warn" | "bad" | "neutral";

export const TONE_COLOR: Record<Tone, string> = {
  good: colors.success,
  warn: colors.needsHuman,
  bad: colors.refused,
  neutral: colors.brass,
};

/** Forest ground, safe areas on the given edges, optional pull to refresh. */
export function Screen({
  children,
  edges = ["top", "left", "right"],
  refreshing,
  onRefresh,
}: {
  children: ReactNode;
  edges?: Edge[];
  refreshing?: boolean;
  onRefresh?: () => void;
}) {
  return (
    <SafeAreaView style={styles.screen} edges={edges}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          onRefresh ? <RefreshControl refreshing={Boolean(refreshing)} onRefresh={onRefresh} tintColor={colors.paperDeep} /> : undefined
        }
      >
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

export function PaperCard({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[styles.card, style]}>
      <ImageBackground source={paperTexture} resizeMode="repeat" style={StyleSheet.absoluteFill} imageStyle={styles.texture} />
      {children}
    </View>
  );
}

export function Title({ children, light }: { children: ReactNode; light?: boolean }) {
  return (
    <Text accessibilityRole="header" maxFontSizeMultiplier={1.4} style={[styles.title, light && { color: colors.paperLight }]}>
      {children}
    </Text>
  );
}

export function Body({
  children,
  soft,
  strong,
  light,
  style,
}: {
  children: ReactNode;
  soft?: boolean;
  strong?: boolean;
  light?: boolean;
  style?: StyleProp<TextStyle>;
}) {
  return (
    <Text
      style={[
        styles.body,
        soft && { color: colors.inkSoft },
        strong && { fontFamily: fonts.semibold },
        light && { color: colors.paperLight },
        style,
      ]}
    >
      {children}
    </Text>
  );
}

export function Mono({ children, style }: { children: ReactNode; style?: StyleProp<TextStyle> }) {
  return <Text style={[styles.mono, style]}>{children}</Text>;
}

export function Button({
  label,
  onPress,
  disabled,
  secondary,
  hint,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  secondary?: boolean;
  hint?: string;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: Boolean(disabled) }}
      accessibilityHint={hint}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        secondary ? styles.buttonSecondary : styles.buttonPrimary,
        disabled && styles.buttonDisabled,
        pressed && !disabled && styles.buttonPressed,
      ]}
    >
      <Text style={[styles.buttonText, secondary && { color: colors.ink }]}>{label}</Text>
    </Pressable>
  );
}

/** A status line that screen readers announce when it changes. */
export function StatusPill({ tone, label, detail }: { tone: Tone; label: string; detail?: string | null }) {
  return (
    <View accessibilityLiveRegion="polite" style={styles.pill}>
      <View style={[styles.dot, { backgroundColor: TONE_COLOR[tone] }]} />
      <View style={styles.pillTextWrap}>
        <Text style={styles.pillText}>{label}</Text>
        {detail ? <Text style={styles.pillDetail}>{detail}</Text> : null}
      </View>
    </View>
  );
}

/** A bordered message on paper. Warnings and failures are announced as alerts. */
export function Notice({ tone, title, children }: { tone: Tone; title: string; children?: ReactNode }) {
  return (
    <View
      accessibilityRole={tone === "bad" || tone === "warn" ? "alert" : undefined}
      style={[styles.notice, { borderLeftColor: TONE_COLOR[tone] }]}
    >
      <Text style={[styles.noticeTitle, { color: tone === "neutral" ? colors.ink : TONE_COLOR[tone] }]}>{title}</Text>
      {children ? <View style={{ marginTop: space.xs }}>{typeof children === "string" ? <Body>{children}</Body> : children}</View> : null}
    </View>
  );
}

/** A filled verdict bar, the loudest statement on a screen. */
export function Verdict({ tone, children, announce = true }: { tone: Tone; children: ReactNode; announce?: boolean }) {
  const background = tone === "neutral" ? colors.paperDeep : TONE_COLOR[tone];
  return (
    <View accessibilityLiveRegion={announce ? "polite" : "none"} style={[styles.verdict, { backgroundColor: background }]}>
      <Text style={[styles.verdictText, tone === "neutral" && { color: colors.ink }]}>{children}</Text>
    </View>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      {typeof children === "string" ? <Body strong>{children}</Body> : children}
    </View>
  );
}

/** A truncated hash that copies its full value. Missing values say so instead of inventing one. */
export function Hash({ value, label }: { value: string | null; label: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  if (!value) return <Text style={styles.notReported}>not reported</Text>;

  const copy = async () => {
    try {
      await Clipboard.setStringAsync(value);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      console.warn("[PriceQuorum] copy failed", err);
    }
  };

  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`Copy ${label}`} onPress={copy} style={styles.hash}>
      <Text style={styles.mono}>{truncateHash(value)}</Text>
      <Text style={styles.copyHint}>{copied ? "copied" : "copy"}</Text>
    </Pressable>
  );
}

export function ChapterCard({ index, title, children }: { index: number; title: string; children: ReactNode }) {
  return (
    <PaperCard>
      <View style={styles.chapterHead}>
        <Text style={styles.chapterIndex}>{String(index).padStart(2, "0")}</Text>
        <Text accessibilityRole="header" maxFontSizeMultiplier={1.5} style={styles.chapterTitle}>
          {title}
        </Text>
      </View>
      {children}
    </PaperCard>
  );
}

export function Loading({ label }: { label: string }) {
  return (
    <View accessibilityLiveRegion="polite" style={styles.loading}>
      <ActivityIndicator color={colors.olive} />
      <Body soft>{label}</Body>
    </View>
  );
}

export function healthSummary(health: HealthCheck | null): { tone: Tone; label: string; detail: string | null } {
  if (!health) return { tone: "neutral", label: "Checking the backend", detail: null };
  switch (health.state) {
    case "healthy":
      return { tone: "good", label: "Backend online", detail: null };
    case "degraded":
      return { tone: "warn", label: "Backend degraded", detail: health.problems.join(", ") };
    case "unreachable":
      return { tone: "bad", label: "Backend offline", detail: health.status === null ? null : `answered with status ${health.status}` };
    case "unconfigured":
      return { tone: "warn", label: "Backend not configured", detail: "Add its address in Settings" };
  }
}

export const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.forest },
  scroll: { padding: space.lg, gap: space.lg, paddingBottom: space.xxl },
  card: {
    backgroundColor: colors.paper,
    borderRadius: 10,
    padding: space.lg,
    gap: space.md,
    overflow: "hidden",
  },
  texture: { opacity: 0.55 },
  title: { fontFamily: fonts.display, fontSize: 30, lineHeight: 34, color: colors.ink, textTransform: "uppercase" },
  body: { fontFamily: fonts.body, fontSize: 16, lineHeight: 24, color: colors.ink },
  mono: { fontFamily: fonts.mono, fontSize: 14, color: colors.ink },
  button: {
    minHeight: TOUCH,
    borderRadius: 8,
    paddingHorizontal: space.xl,
    paddingVertical: space.md,
    alignItems: "center",
    justifyContent: "center",
  },
  // Olive, not forest: forest is the screen ground, where a forest button read as plain text.
  buttonPrimary: { backgroundColor: colors.olive, borderWidth: 1.5, borderColor: colors.paperDeep },
  buttonSecondary: { backgroundColor: "transparent", borderWidth: 1.5, borderColor: colors.ink },
  buttonDisabled: { opacity: 0.5 },
  buttonPressed: { opacity: 0.8 },
  buttonText: { fontFamily: fonts.semibold, fontSize: 17, color: colors.paperLight },
  pill: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: space.sm,
    borderRadius: 999,
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
    backgroundColor: "rgba(0,0,0,0.25)",
    maxWidth: "100%",
  },
  dot: { width: 10, height: 10, borderRadius: 5 },
  pillTextWrap: { flexShrink: 1 },
  pillText: { fontFamily: fonts.semibold, fontSize: 15, color: colors.paperLight },
  pillDetail: { fontFamily: fonts.body, fontSize: 13, color: colors.paperDeep },
  notice: {
    borderLeftWidth: 4,
    backgroundColor: "rgba(246,240,225,0.8)",
    borderRadius: 6,
    paddingHorizontal: space.md,
    paddingVertical: space.md,
  },
  noticeTitle: { fontFamily: fonts.semibold, fontSize: 16, lineHeight: 22 },
  verdict: { borderRadius: 8, paddingHorizontal: space.lg, paddingVertical: space.md },
  verdictText: { fontFamily: fonts.semibold, fontSize: 17, lineHeight: 24, color: colors.paperLight },
  field: { gap: 2 },
  fieldLabel: { fontFamily: fonts.body, fontSize: 13, color: colors.inkSoft },
  hash: { flexDirection: "row", alignItems: "center", gap: space.sm, minHeight: TOUCH, alignSelf: "flex-start" },
  copyHint: { fontFamily: fonts.semibold, fontSize: 13, color: colors.olive, textDecorationLine: "underline" },
  notReported: { fontFamily: fonts.body, fontSize: 15, color: colors.inkSoft },
  chapterHead: { flexDirection: "row", alignItems: "baseline", gap: space.md },
  chapterIndex: { fontFamily: fonts.display, fontSize: 28, color: colors.olive },
  chapterTitle: { flex: 1, fontFamily: fonts.display, fontSize: 20, lineHeight: 24, color: colors.ink, textTransform: "uppercase" },
  loading: { flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: space.sm },
});
