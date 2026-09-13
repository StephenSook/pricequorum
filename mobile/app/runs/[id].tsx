import { Stack, useLocalSearchParams } from "expo-router";
import { View } from "react-native";

import { useRunEvents, type StreamState } from "../../src/api/useRunEvents";
import { useBackend } from "../../src/backend";
import { Approve, Migrate, Receipt, Resolve, Verify } from "../../src/run/chapters";
import { currentChapter } from "../../src/shared/api/events";
import { Body, Loading, Notice, Screen, StatusPill, type Tone } from "../../src/ui/components";
import { colors } from "../../src/ui/theme";

const RUN_ID = /^[A-Za-z0-9-]{8,64}$/;

const STREAM_LABEL: Record<StreamState, string> = {
  idle: "Not connected",
  connecting: "Connecting to the run",
  open: "Live",
  retrying: "Backend not answering, retrying",
  reconnecting: "Connection dropped, reconnecting",
  closed: "Run finished",
  failed: "Stream stopped",
  unavailable: "Backend address not configured",
};

const WAITING_TEXT: Record<StreamState, string> = {
  idle: "Not connected.",
  connecting: "Connecting to the run.",
  open: "Connected. Waiting for the first event from the backend.",
  retrying: "The backend is not answering yet. This screen keeps trying.",
  reconnecting: "The connection dropped. Reconnecting.",
  closed: "The run finished, but none of its events could be loaded.",
  failed: "The backend refused the event stream for this run. The run id may not exist, or the backend returned an error. Go back and open the run again to retry.",
  unavailable: "The backend address is not configured, so this run cannot be loaded. Add it in Settings.",
};

const STREAM_TONE: Partial<Record<StreamState, Tone>> = { open: "good", closed: "neutral", failed: "bad" };

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export default function RunScreen() {
  const params = useLocalSearchParams<{ id: string }>();
  const id = typeof params.id === "string" ? params.id : "";
  const valid = RUN_ID.test(id);
  const { base, loaded } = useBackend();
  const { view, stream, invalidMessages } = useRunEvents(loaded ? base : "", loaded && valid ? id : null);

  const title = valid ? `Run ${id.slice(0, 8)}` : "Run";

  if (!valid) {
    return (
      <Screen edges={["left", "right", "bottom"]}>
        <Stack.Screen options={{ title }} />
        <Notice tone="bad" title="That is not a valid run id. Run ids are letters, digits and hyphens." />
      </Screen>
    );
  }

  if (!loaded || !view) {
    return (
      <Screen edges={["left", "right", "bottom"]}>
        <Stack.Screen options={{ title }} />
        <View style={{ backgroundColor: colors.paper, borderRadius: 10, padding: 16 }}>
          <Loading label="Reading the backend address." />
        </View>
      </Screen>
    );
  }

  const chapter = currentChapter(view);
  const notes = [
    view.unrecognized.length > 0 ? `${plural(view.unrecognized.length, "event")} this app does not display yet` : null,
    view.unplaced.length > 0 ? `${plural(view.unplaced.length, "ledger event")} that named no known step` : null,
    view.rejected.length > 0 ? `${plural(view.rejected.length, "event")} rejected for missing or invalid fields` : null,
    invalidMessages > 0 ? `${plural(invalidMessages, "malformed message")} ignored` : null,
  ].filter(Boolean);

  return (
    <Screen edges={["left", "right", "bottom"]}>
      <Stack.Screen options={{ title }} />
      <StatusPill tone={STREAM_TONE[stream] ?? "warn"} label={STREAM_LABEL[stream]} detail={`run ${id.slice(0, 8)}`} />

      {chapter === "waiting" ? (
        <Notice tone={stream === "failed" ? "bad" : stream === "unavailable" ? "warn" : "neutral"} title={WAITING_TEXT[stream]} />
      ) : null}

      {view.intent || view.resolution || view.policy ? <Resolve view={view} /> : null}
      {view.approval || view.policy ? <Approve view={view} /> : null}
      {view.ledger.length > 0 || view.subscriptions.length > 0 || view.renewalInvoice ? <Migrate view={view} /> : null}
      {view.readbacks.length > 0 || view.invariants.length > 0 ? <Verify view={view} /> : null}
      {view.outcome ? <Receipt view={view} /> : null}

      {notes.length > 0 ? (
        <Body light style={{ fontSize: 13, color: colors.paperDeep, textAlign: "center" }}>
          {notes.join(", ")}.
        </Body>
      ) : null}
    </Screen>
  );
}
