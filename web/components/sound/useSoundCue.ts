import { useEffect, useRef } from "react";

import { currentChapter, type ChapterId, type Outcome, type RunView } from "@/lib/api/events";

import { playCue, type Cue } from "./audio";
import { soundStore } from "./soundStore";

export type CueSnapshot = { chapter: ChapterId; completedSteps: number; outcome: Outcome | null };

const CHAPTER_TEXT: Record<Exclude<ChapterId, "waiting" | "receipt">, string> = {
  resolve: "Working out which plan this change is about.",
  approve: "The approval step has started.",
  migrate: "Writing the change to the apps, one ledger step at a time.",
  verify: "Reading Stripe, Notion and Airtable back.",
};

const OUTCOME_WORDS: Record<Outcome, string> = {
  SUCCESS: "success",
  PARTIAL: "partial",
  REFUSED: "refused",
  NEEDS_HUMAN: "needs a person",
};

export function snapshotOf(view: RunView | null): CueSnapshot {
  if (!view) return { chapter: "waiting", completedSteps: 0, outcome: null };
  return {
    chapter: currentChapter(view),
    completedSteps: view.ledger.filter((step) => step.state === "completed").length,
    outcome: view.outcome?.outcome ?? null,
  };
}

function announcementFor(snapshot: CueSnapshot): string | null {
  if (snapshot.chapter === "waiting") return null;
  if (snapshot.chapter === "receipt") {
    return snapshot.outcome ? `The backend reported the outcome: ${OUTCOME_WORDS[snapshot.outcome]}.` : null;
  }
  return CHAPTER_TEXT[snapshot.chapter];
}

/**
 * What changed between two renders of a run. The first snapshot is a baseline: it announces where the
 * run is but plays nothing, so opening a page never starts with a sound.
 */
export function cuesBetween(previous: CueSnapshot | null, next: CueSnapshot): { cues: Cue[]; announcement: string | null } {
  if (!previous) return { cues: [], announcement: announcementFor(next) };
  const cues: Cue[] = [];
  if (next.outcome && !previous.outcome) cues.push("stamp");
  if (next.completedSteps > previous.completedSteps) cues.push("chain");
  const chapterChanged = next.chapter !== previous.chapter;
  if (chapterChanged && next.chapter !== "receipt" && next.chapter !== "waiting") cues.push("paper");
  const announcement = chapterChanged || next.outcome !== previous.outcome ? announcementFor(next) : null;
  return { cues, announcement };
}

/** Plays a cue and updates the chapter announcement when a real run event moves the run forward. */
export function useSoundCue(view: RunView | null) {
  const { chapter, completedSteps, outcome } = snapshotOf(view);
  const previous = useRef<CueSnapshot | null>(null);

  useEffect(() => {
    const next: CueSnapshot = { chapter, completedSteps, outcome };
    const { cues, announcement } = cuesBetween(previous.current, next);
    previous.current = next;
    if (announcement) soundStore.announce(announcement);
    if (soundStore.getSnapshot().sound) for (const cue of cues) playCue(cue);
  }, [chapter, completedSteps, outcome]);
}
