"use client";

import { useCallback, useEffect, useState } from "react";

import { Ticket } from "@/components/chapters/Ticket";
import { Preloader } from "@/components/motion/Preloader";
import { RoughFrame } from "@/components/motion/RoughFrame";
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

  return (
    <main className="relative flex min-h-svh flex-1 items-center justify-center overflow-hidden py-16">
      <div
        aria-hidden="true"
        className="fixed inset-0 z-[var(--z-canvas)] bg-cover bg-center"
        style={{
          backgroundImage:
            "linear-gradient(rgb(35 40 11 / 0.35), rgb(35 40 11 / 0.55)), url(/scenes/ledger-desk.webp), url(/textures/ink-paper-dark.webp)",
        }}
      />
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
      ) : (
        <section
          aria-live="polite"
          className="relative z-[var(--z-content)] mx-4 max-w-xl rounded-lg bg-forest/90 px-6 py-8 text-center text-paper-light"
        >
          <p className="text-lg font-semibold">Run accepted by the backend.</p>
          <p className="mt-2 text-paper-deep">Waiting for its first event.</p>
          <p className="type-hash mt-4 break-all text-sm text-brass">{runId}</p>
        </section>
      )}

      {health && preloaderGone ? (
        <p
          role="status"
          className="fixed right-8 top-8 z-[var(--z-overlay)] flex items-center gap-2 rounded-full bg-forest/90 px-4 py-2 text-sm text-paper-deep"
        >
          <span
            aria-hidden="true"
            className={health.reachable ? "h-2 w-2 rounded-full bg-outcome-success" : "h-2 w-2 rounded-full bg-outcome-needs-human"}
          />
          {health.reachable ? "Backend online" : "Backend offline"}
        </p>
      ) : null}

      {!preloaderGone ? <Preloader ready={ready} onGone={() => setPreloaderGone(true)} /> : null}
    </main>
  );
}
