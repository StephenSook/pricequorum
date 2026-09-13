"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { API_BASE, checkHealth } from "@/lib/api/client";

type Health = "checking" | "online" | "degraded" | "offline";
type StopState = Health | "unanswered" | "public";

const REPO = "https://github.com/StephenSook/pricequorum";
const PROBE_TIMEOUT_MS = 8000;

type Stop = {
  title: string;
  what: string;
  href: string;
  external?: boolean;
  /**
   * When this stop is shown as live, checked in this browser:
   * - "health": the /api/health body reports every part up.
   * - an API path: health is up and that endpoint answers with JSON.
   * - "public": needs nothing from the backend.
   */
  check: "health" | `/api/${string}` | "public";
};

const STOPS: Stop[] = [
  {
    title: "Ask for a price change",
    what: "Type a change in plain words on the home page. The backend asks Slack for approval before anything is written.",
    href: "/",
    check: "health",
  },
  {
    title: "Watch the run",
    what: "Each chapter appears only when the backend reports that step: resolve the plan, approval, the writes, the read-backs, the receipt.",
    href: "/",
    check: "health",
  },
  {
    title: "Check the ledger in your browser",
    what: "The page recomputes every entry hash and checks the Ed25519 signature on the head without trusting the server.",
    href: "/verify",
    check: "/api/ledger/export",
  },
  {
    title: "See the evaluation results",
    what: "The scenario pass rate with its confidence interval, refusals, duplicate writes prevented and every named failure.",
    href: "/evals",
    check: "/api/proof",
  },
  {
    title: "Read the source and CI",
    what: "The repository, every commit and every workflow run are public.",
    href: REPO,
    external: true,
    check: "public",
  },
];

const COMMANDS = ["/api/health", "/api/proof", "/api/ledger/export"];

const BADGE: Record<StopState, { label: string; className: string }> = {
  online: { label: "Live now", className: "bg-outcome-success text-paper-light" },
  public: { label: "Public", className: "bg-outcome-success text-paper-light" },
  checking: { label: "Checking the backend", className: "bg-ink/10 text-ink" },
  degraded: { label: "Backend degraded", className: "bg-outcome-needs-human text-paper-light" },
  unanswered: { label: "Endpoint not answering", className: "bg-outcome-needs-human text-paper-light" },
  offline: { label: "Waiting on the backend", className: "bg-forest text-paper-light" },
};

async function answersWithJson(path: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) });
    if (!res.ok) return false;
    await res.json();
    return true;
  } catch {
    return false;
  }
}

function stateOf(stop: Stop, health: Health, endpoints: Record<string, boolean>): StopState {
  if (stop.check === "public") return "public";
  if (health !== "online") return health;
  if (stop.check === "health") return "online";
  const answered = endpoints[stop.check];
  return answered === undefined ? "checking" : answered ? "online" : "unanswered";
}

export function JudgeTour() {
  const [health, setHealth] = useState<Health>(API_BASE ? "checking" : "offline");
  const [endpoints, setEndpoints] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!API_BASE) return;
    let cancelled = false;
    // Live only when the health body says every part is up; a bare 200 is not enough.
    checkHealth(PROBE_TIMEOUT_MS).then((result) => {
      if (!cancelled) setHealth(result.state === "healthy" ? "online" : result.state === "degraded" ? "degraded" : "offline");
    });
    const paths = STOPS.flatMap((stop) => (stop.check.startsWith("/api/") ? [stop.check] : []));
    Promise.all(paths.map(async (path) => [path, await answersWithJson(path)] as const)).then((pairs) => {
      if (!cancelled) setEndpoints(Object.fromEntries(pairs));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <ol className="mt-8 space-y-4">
        {STOPS.map((stop, index) => {
          const badge = BADGE[stateOf(stop, health, endpoints)];
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
          {health === "online"
            ? "These endpoints need no credentials."
            : health === "checking"
              ? "Checking whether the backend is reachable."
              : health === "degraded"
                ? "The backend answers but reports a problem, so some of these may not work right now."
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
