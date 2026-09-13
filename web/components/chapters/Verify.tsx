import { ChapterFrame } from "@/components/chapters/ChapterFrame";
import type { Readback, RunView } from "@/lib/api/events";
import { formatMinor } from "@/lib/format";

const APPS = [
  { key: "stripe", name: "Stripe", role: "billing" },
  { key: "notion", name: "Notion", role: "pricing page" },
  { key: "airtable", name: "Airtable", role: "catalogue" },
] as const;

type PricedReadback = Readback & { minorUnits: number; currency: string };

const priced = (r: Readback | undefined): r is PricedReadback => r !== undefined && r.minorUnits !== null && r.currency !== null;

const TONE_CLASS = {
  good: "bg-outcome-success text-paper-light",
  bad: "bg-outcome-refused text-paper-light",
  neutral: "bg-ink/10 text-ink",
} as const;

export function Verify({ view }: { view: RunView }) {
  const byApp = new Map(view.readbacks.map((r) => [r.app, r]));
  const values = APPS.map((app) => byApp.get(app.key));
  const allReported = values.every((r) => r !== undefined);
  const pricedValues = values.filter(priced);
  const first = pricedValues[0];
  const allPriced = pricedValues.length === APPS.length;
  const agree = allPriced && pricedValues.every((r) => r.minorUnits === first.minorUnits && r.currency === first.currency);
  const allFresh = values.every((r) => r?.fresh === true);
  // A check that reported no result is not a pass.
  const failing = view.invariants.filter((i) => i.ok !== true);
  const invariantsOk = view.invariants.length > 0 && failing.length === 0;

  let tone: keyof typeof TONE_CLASS = "neutral";
  let message = "Waiting for every app to be read back.";
  if (agree && invariantsOk && allFresh && first) {
    tone = "good";
    message = `All three agree: ${formatMinor(first.minorUnits, first.currency)}, read back fresh from each app.`;
  } else if (agree && invariantsOk) {
    tone = "bad";
    message = "The values agree, but not every app reported a fresh read, so this run cannot be called a success.";
  } else if (allReported && !allPriced) {
    tone = "bad";
    message = "At least one app was read but returned no price. This run cannot be called a success.";
  } else if (allPriced && !agree) {
    tone = "bad";
    message = "The apps disagree. This run cannot be called a success.";
  } else if (failing.length > 0) {
    tone = "bad";
    message = `${failing.length} check${failing.length === 1 ? "" : "s"} failed or reported no result.`;
  } else if (agree) {
    message = "The three values agree. Waiting for the invariant checks.";
  }

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
                {priced(r) ? formatMinor(r.minorUnits, r.currency) : r ? "no price found" : "not read yet"}
              </p>
              {r?.rawValue ? <p className="type-hash mt-1 text-xs text-ink-soft">stored as {r.rawValue}</p> : null}
            </li>
          );
        })}
      </ul>

      <div role="status" className={`mt-5 rounded-md px-5 py-4 text-lg font-semibold ${TONE_CLASS[tone]}`}>
        {message}
      </div>

      {view.invariants.length > 0 ? (
        <ul className="mt-4 space-y-1 text-sm">
          {view.invariants.map((inv, index) => (
            <li key={`${inv.name ?? "unnamed"}-${index}`} className="flex gap-2">
              <span className={inv.ok === true ? "text-outcome-success" : "text-outcome-refused"}>
                {inv.ok === true ? "passed" : inv.ok === false ? "failed" : "no result"}
              </span>
              <span className="type-hash">{inv.name ?? "unnamed check"}</span>
              {inv.detail ? <span className="text-ink-soft">{inv.detail}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </ChapterFrame>
  );
}
