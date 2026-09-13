"use client";

import { unlockAudio } from "./audio";
import { soundStore, useSoundPreferences } from "./soundStore";

const TOGGLE =
  "flex min-h-11 cursor-pointer items-center gap-2 rounded-full bg-forest/90 px-4 text-sm font-semibold text-paper-light transition-colors duration-200 hover:bg-olive";

/**
 * Sound and subtitle toggles for pages that show a live run. Both start off. Chapter changes are
 * always announced to screen readers; the visible subtitle line appears only when switched on.
 */
export function SoundControls() {
  const prefs = useSoundPreferences();

  return (
    <>
      {/* Bottom right, above the drift strip, clear of the health and stream pills at the top. */}
      <div className="fixed bottom-14 right-4 z-[var(--z-overlay)] flex gap-2">
        <button
          type="button"
          aria-pressed={prefs.sound}
          onClick={() => {
            if (!prefs.sound) unlockAudio();
            soundStore.setSound(!prefs.sound);
          }}
          className={TOGGLE}
        >
          Sound <span className="font-normal text-paper-deep">{prefs.sound ? "on" : "off"}</span>
        </button>
        <button type="button" aria-pressed={prefs.subtitles} onClick={() => soundStore.setSubtitles(!prefs.subtitles)} className={TOGGLE}>
          Subtitles <span className="font-normal text-paper-deep">{prefs.subtitles ? "on" : "off"}</span>
        </button>
      </div>

      {prefs.subtitles && prefs.announcement ? (
        <p
          aria-hidden="true"
          className="fixed inset-x-4 bottom-28 z-[var(--z-overlay)] mx-auto w-fit max-w-[60ch] rounded-md bg-ink/90 px-4 py-2 text-center text-paper-light"
        >
          {prefs.announcement}
        </p>
      ) : null}
      <p aria-live="polite" className="sr-only">
        {prefs.announcement}
      </p>
    </>
  );
}
