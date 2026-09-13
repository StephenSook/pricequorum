import { ChapterFrame } from "@/components/chapters/ChapterFrame";
import type { RunView } from "@/lib/api/events";
import { formatMinor } from "@/lib/format";

const APPS = [
  { key: "stripe", name: "Stripe", role: "billing" },
  { key: "notion", name: "Notion", role: "pricing page" },
  { key: "airtable", name: "Airtable", role: "catalogue" },
] as const;

export function Verify({ view }: { view: RunView }) {
  const byApp = new Map(view.readbacks.map((r) => [r.app, r]));
  const values = APPS.map((app) => byApp.get(app.key));
  const allRead = values.every((r) => r && r.minorUnits !== null && r.currency);
  const agree =
    allRead &&
    values.every((r) => r!.minorUnits === values[0]!.minorUnits && r!.currency === values[0]!.currency);
  const failing = view.invariants.filter((i) => i.ok === false);
  const invariantsOk = view.invariants.length > 0 && failing.length === 0;

  return (
    <ChapterFrame index={4} title="Read all three back" tone="forest">
      <ul className="grid gap-3 sm:grid-cols-3">
        {APPS.map((app, i) => {
          const r = values[i];
          return (
            <li key={app.key} className="rounded-md border border-ink/15 bg-paper-light/80 px-4 py-4">
              <p className="font-semibold">
                {app.name} <span className="font-normal text-ink-soft">{app.role}</span>
              </p>
              <p className="type-display mt-2 text-[clamp(1.4rem,2.6vw,2rem)] text-ink [text-shadow:none]">
                {r && r.minorUnits !== null && r.currency ? formatMinor(r.minorUnits, r.currency) : "not read yet"}
              </p>
              {r?.rawValue ? <p className="type-hash mt-1 text-xs text-ink-soft">stored as {r.rawValue}</p> : null}
            </li>
          );
        })}
      </ul>

      <div
        role="status"
        className={`mt-5 rounded-md px-5 py-4 text-lg font-semibold ${
          agree && invariantsOk
            ? "bg-outcome-success text-paper-light"
            : failing.length > 0 || (allRead && !agree)
              ? "bg-outcome-refused text-paper-light"
              : "bg-ink/10 text-ink"
        }`}
      >
        {agree && invariantsOk
          ? `All three agree: ${formatMinor(values[0]!.minorUnits!, values[0]!.currency!)}, read back fresh from each app.`
          : allRead && !agree
            ? "The apps disagree. This run cannot be called a success."
            : failing.length > 0
              ? `${failing.length} check${failing.length === 1 ? "" : "s"} failed.`
              : "Waiting for every app to be read back."}
      </div>

      {view.invariants.length > 0 ? (
        <ul className="mt-4 space-y-1 text-sm">
          {view.invariants.map((inv) => (
            <li key={inv.name ?? inv.detail ?? "invariant"} className="flex gap-2">
              <span className={inv.ok ? "text-outcome-success" : "text-outcome-refused"}>{inv.ok ? "passed" : "failed"}</span>
              <span className="type-hash">{inv.name ?? "unnamed check"}</span>
              {inv.detail ? <span className="text-ink-soft">{inv.detail}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </ChapterFrame>
  );
}
