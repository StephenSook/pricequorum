import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

const STORAGE_KEY = "pricequorum.backendUrl";

/** Trims and strips trailing slashes. Returns "" for empty input and null for an address that is not http(s). */
export function normalizeBase(value: string): string | null {
  const trimmed = value.trim().replace(/\/+$/, "");
  if (!trimmed) return "";
  return /^https?:\/\/[^\s/]+/i.test(trimmed) ? trimmed : null;
}

const BUILD_BASE = normalizeBase(process.env.EXPO_PUBLIC_API_BASE_URL ?? "") ?? "";

export type BackendSource = "settings" | "build" | "none";

type Backend = {
  /** The backend address in use, or "" when none is set. */
  base: string;
  source: BackendSource;
  buildBase: string;
  /** False until the saved address has been read, so screens do not flash "not configured". */
  loaded: boolean;
  save: (value: string) => Promise<void>;
  reset: () => Promise<void>;
};

const BackendContext = createContext<Backend | null>(null);

/**
 * Where the app finds the backend: an address saved in Settings wins, then the address baked in
 * at build time (EXPO_PUBLIC_API_BASE_URL). A build can be pointed at a new backend without a rebuild.
 */
export function BackendProvider({ children }: { children: ReactNode }) {
  const [saved, setSaved] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    AsyncStorage.getItem(STORAGE_KEY)
      .then((value) => {
        if (cancelled) return;
        const normalized = value ? normalizeBase(value) : null;
        setSaved(normalized ? normalized : null);
        setLoaded(true);
      })
      .catch((err) => {
        console.warn("[PriceQuorum] could not read the saved backend address", err);
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const save = useCallback(async (value: string) => {
    const normalized = normalizeBase(value);
    if (normalized === null) throw new Error("Enter an address that starts with https:// or http://.");
    if (normalized === "") {
      await AsyncStorage.removeItem(STORAGE_KEY);
      setSaved(null);
      return;
    }
    await AsyncStorage.setItem(STORAGE_KEY, normalized);
    setSaved(normalized);
  }, []);

  const reset = useCallback(async () => {
    await AsyncStorage.removeItem(STORAGE_KEY);
    setSaved(null);
  }, []);

  const value = useMemo<Backend>(() => {
    const source: BackendSource = saved ? "settings" : BUILD_BASE ? "build" : "none";
    return { base: saved ?? BUILD_BASE, source, buildBase: BUILD_BASE, loaded, save, reset };
  }, [saved, loaded, save, reset]);

  return <BackendContext.Provider value={value}>{children}</BackendContext.Provider>;
}

export function useBackend(): Backend {
  const backend = useContext(BackendContext);
  if (!backend) throw new Error("useBackend must be used inside BackendProvider");
  return backend;
}
