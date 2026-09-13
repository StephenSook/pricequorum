"use client";

import { useCallback, useEffect, useState } from "react";

import { Ticket } from "@/components/chapters/Ticket";
import { Preloader } from "@/components/motion/Preloader";
import { RoughFrame } from "@/components/motion/RoughFrame";
import { SceneBackdrop } from "@/components/motion/SceneBackdrop";
import { RunStage } from "@/components/RunStage";
import { ApiError, checkHealth, createRun, type HealthCheck } from "@/lib/api/client";

const PRELOAD_IMAGES = [
  "/textures/marbled-endpaper.webp",
  "/textures/paper-grain.webp",
  "/textures/ink-paper-dark.webp",
  "/scenes/ledger-desk.webp",
];

function preloadImage(src: string): Promise<void> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve();
    img.onerror = () => resolve();
    img.src = src;
  });
}

function healthPill(health: HealthCheck): { dot: string; text: string } {
  switch (health.state) {
    case "healthy":
      return { dot: "bg-outcome-success", text: "Backend online" };
    case "degraded":
      return { dot: "bg-outcome-needs-human", text: `Backend degraded: ${health.problems.join(", ")}` };
    case "unreachable":
      return { dot: "bg-outcome-refused", text: "Backend offline" };
    case "unconfigured":
      return { dot: "bg-outcome-needs-human", text: "Backend not configured" };
  }
}

type RunError = { message: string; remedy: string | null };

export function Experience() {
  const [ready, setReady] = useState(false);
  const [health, setHealth] = useState<HealthCheck | null>(null);
  const [preloaderGone, setPreloaderGone] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<RunError | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [ticketGone, setTicketGone] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([document.fonts.ready, ...PRELOAD_IMAGES.map(preloadImage), checkHealth(3500)]).then((results) => {
      if (cancelled) return;
      setHealth(results[results.length - 1] as HealthCheck);
      setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = useCallback(async (requestText: string) => {
    setSubmitting(true);
    setError(null);
    try {
      const created = await createRun(requestText);
      setRunId(created.runId);
      // The address bar now names this run, so a refresh or a shared link opens its receipt.
      window.history.replaceState(null, "", `/runs/${encodeURIComponent(created.runId)}`);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? { message: err.message, remedy: err.remedy }
          : { message: "The request could not be sent.", remedy: "Check your connection and try again." },
      );
    } finally {
      setSubmitting(false);
    }
  }, []);

  const pill = health ? healthPill(health) : null;

  return (
    <main className="relative flex min-h-svh flex-1 items-center justify-center overflow-hidden py-16">
      <SceneBackdrop dim="light" />
      <RoughFrame />

      {!ticketGone ? (
        <Ticket
          active={preloaderGone}
          leaving={runId !== null}
          submitting={submitting}
          error={error}
          onSubmit={handleSubmit}
          onExited={() => setTicketGone(true)}
        />
      ) : runId ? (
        <RunStage runId={runId} />
      ) : null}

      {pill && preloaderGone ? (
        <p
          role="status"
          className="fixed right-8 top-8 z-[var(--z-overlay)] flex max-w-[calc(100vw-4rem)] items-center gap-2 rounded-full bg-forest/90 px-4 py-2 text-sm text-paper-deep"
        >
          <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${pill.dot}`} />
          {pill.text}
        </p>
      ) : null}

      {!preloaderGone ? <Preloader ready={ready} onGone={() => setPreloaderGone(true)} /> : null}
    </main>
  );
}
