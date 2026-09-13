import { useSyncExternalStore } from "react";

/**
 * Sound and subtitle preferences plus the latest chapter announcement, shared by the run hook and the
 * controls. Sound is off by default. Preferences persist in localStorage when the browser allows it.
 */
export type SoundState = { sound: boolean; subtitles: boolean; announcement: string };

const STORAGE_KEY = "pq-sound-preferences";
const SERVER_STATE: SoundState = { sound: false, subtitles: false, announcement: "" };

let state: SoundState = SERVER_STATE;
let loaded = false;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function load() {
  if (loaded || typeof window === "undefined") return;
  loaded = true;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const saved: unknown = JSON.parse(raw);
    if (typeof saved === "object" && saved !== null) {
      const record = saved as Record<string, unknown>;
      state = { ...state, sound: record.sound === true, subtitles: record.subtitles === true };
    }
  } catch {
    // Storage can be blocked (private mode, disabled site data). The defaults stay in place.
  }
}

function save() {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ sound: state.sound, subtitles: state.subtitles }));
  } catch {
    // Storage can be blocked; the preference then lasts for this page only.
  }
}

export const soundStore = {
  subscribe(listener: () => void) {
    load();
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  getSnapshot(): SoundState {
    return state;
  },
  getServerSnapshot(): SoundState {
    return SERVER_STATE;
  },
  setSound(on: boolean) {
    state = { ...state, sound: on };
    save();
    emit();
  },
  setSubtitles(on: boolean) {
    state = { ...state, subtitles: on };
    save();
    emit();
  },
  announce(text: string) {
    if (text === state.announcement) return;
    state = { ...state, announcement: text };
    emit();
  },
};

export function useSoundPreferences(): SoundState {
  return useSyncExternalStore(soundStore.subscribe, soundStore.getSnapshot, soundStore.getServerSnapshot);
}
