"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { API_BASE, checkHealth } from "@/lib/api/client";

type Probe = "checking" | "online" | "offline";

const REPO = "https://github.com/StephenSook/pricequorum";

type Stop = {
  title: string;
  what: string;
  href: string;
  external?: boolean;
  /** A stop that needs the backend is only shown as live after a health check succeeds in this browser. */
  needsBackend: boolean;
};

const STOPS: Stop[] = [
  {
    title: "Ask for a price change",
    what: "Type a change in plain words on the home page. The backend asks Slack for approval before anything is written.",
    href: "/",
    needsBackend: true,
  },
  {
    title: "Watch the run",
    what: "Each chapter appears only when the backend reports that step: resolve the plan, approval, the writes, the read-backs, the receipt.",
    href: "/",
    needsBackend: true,
  },
  {
    title: "Check the ledger in your browser",
    what: "The page recomputes every entry hash and checks the Ed25519 signature on the head without trusting the server.",
    href: "/verify",
    needsBackend: true,
  },
  {
    title: "See the evaluation results",
    what: "The scenario pass rate with its confidence interval, refusals, duplicate writes prevented and every named failure.",
    href: "/evals",
    needsBackend: true,
  },
  {
    title: "Read the source and CI",
    what: "The repository, every commit and every workflow run are public.",
    href: REPO,
    external: true,
    needsBackend: false,
  },
];

const COMMANDS = ["/api/health", "/api/proof", "/api/ledger/export"];

const BADGE: Record<Probe, { label: string; className: string }> = {
  online: { label: "Live now", className: "bg-outcome-success text-paper-light" },
  checking: { label: "Checking the backend", className: "bg-ink/10 text-ink" },
  offline: { label: "Waiting on the backend", className: "bg-forest text-paper-light" },
};

export function JudgeTour() {
  const [probe, setProbe] = useState<Probe>(API_BASE ? "checking" : "offline");

  useEffect(() => {
    if (!API_BASE) return;
    let cancelled = false;
    checkHealth(5000).then((health) => {
      if (!cancelled) setProbe(health.reachable ? "online" : "offline");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <ol className="mt-8 space-y-4">
        {STOPS.map((stop, index) => {
          const badge = stop.needsBackend ? BADGE[probe] : BADGE.online;
          const linkClass = "text-lg font-semibold underline decoration-olive/40 underline-offset-4 hover:decoration-olive";
          return (
            <li key={stop.title} className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-x-4 rounded-md border border-ink/15 bg-paper-light/70 p-4">
              <span className="type-display text-3xl text-olive [text-shadow:none]">{index + 1}</span>
              <div>
                <div className="flex flex-wrap items-center gap-3">
                  {stop.external ? (
                    <a href={stop.href} className={linkClass}>
                      {stop.title}
                    </a>
                  ) : (
                    <Link href={stop.href} className={linkClass}>
                      {stop.title}
                    </Link>
                  )}
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${badge.className}`}>{badge.label}</span>
                </div>
                <p className="mt-1 text-ink-soft">{stop.what}</p>
              </div>
            </li>
          );
        })}
      </ol>

      <section className="mt-8">
        <h2 className="text-lg font-semibold">Check it from a terminal</h2>
        <p className="mt-1 text-ink-soft">
          {probe === "online"
            ? "These endpoints need no credentials."
            : probe === "checking"
              ? "Checking whether the backend is reachable."
              : "The backend is not reachable yet, so these commands will work once it is deployed."}
        </p>
        {/* Scrolls sideways on narrow screens, so it must be reachable and named for keyboard users. */}
        <pre
          tabIndex={0}
          role="region"
          aria-label="Terminal commands"
          className="type-hash mt-3 overflow-x-auto whitespace-pre-wrap break-all rounded-md bg-forest px-4 py-3 text-sm text-paper-light sm:whitespace-pre sm:break-normal"
        >
          {COMMANDS.map((path) => `curl -s ${API_BASE || "<backend-url>"}${path}`).join("\n")}
        </pre>
      </section>
    </>
  );
}
