import { ChapterFrame } from "@/components/chapters/ChapterFrame";
import { CopyHash } from "@/components/ui/CopyHash";
import type { RunView } from "@/lib/api/events";
import { formatMinor } from "@/lib/format";

const DECIDED_BY: Record<string, string> = {
  exact_id: "matched on the shared pq_plan_id",
  fuzzy: "matched by name similarity",
  human: "confirmed by a person",
};

export function Resolve({ view }: { view: RunView }) {
  const { intent, resolution, policy } = view;
  const ids = [
    { app: "Stripe", label: "Product", value: resolution?.stripeProductId ?? null },
    { app: "Stripe", label: "Current price", value: resolution?.stripePriceId ?? null },
    { app: "Notion", label: "Pricing page", value: resolution?.notionPageId ?? null },
    { app: "Airtable", label: "Catalogue record", value: resolution?.airtableRecordId ?? null },
  ];
  const needsHuman = policy?.decision === "NEEDS_HUMAN" && !resolution;

  return (
    <ChapterFrame
      index={1}
      title="Find the plan in all three apps"
      tone="olive"
      aside={
        <dl className="space-y-4 rounded-md border border-ink/15 bg-paper-light/60 p-4">
          <div>
            <dt className="text-sm text-ink-soft">Request</dt>
            <dd className="mt-1 font-semibold">{view.requestText ?? "not reported"}</dd>
          </div>
          <div>
            <dt className="text-sm text-ink-soft">Understood as</dt>
            <dd className="mt-1 font-semibold">
              {intent && intent.minorUnits !== null && intent.currency
                ? `${intent.planHint ?? "plan"} to ${formatMinor(intent.minorUnits, intent.currency)}${intent.interval ? ` per ${intent.interval}` : ""}`
                : "waiting for the parsed intent"}
            </dd>
          </div>
        </dl>
      }
    >
      <ul className="grid gap-3 sm:grid-cols-2">
        {ids.map((id) => (
          <li key={id.label} className="rounded-md border border-ink/15 bg-paper-light/70 px-4 py-3">
            <p className="text-sm text-ink-soft">
              {id.app} <span className="text-ink-soft/70">{id.label.toLowerCase()}</span>
            </p>
            <div className="mt-1">
              <CopyHash value={id.value} label={`${id.app} ${id.label}`} />
            </div>
          </li>
        ))}
      </ul>

      {resolution ? (
        <p className="mt-5 text-base">
          <span className="type-display text-3xl text-olive [text-shadow:none]">{resolution.confidence ?? "?"}</span>
          <span className="ml-2 text-ink-soft">
            confidence, {resolution.decidedBy ? (DECIDED_BY[resolution.decidedBy] ?? resolution.decidedBy) : "method not reported"}
          </span>
        </p>
      ) : null}

      {needsHuman ? (
        <div role="alert" className="mt-5 rounded-md border-2 border-outcome-needs-human/60 bg-outcome-needs-human/10 px-4 py-3">
          <p className="font-semibold text-outcome-needs-human">Stopped: the plan could not be matched with confidence.</p>
          {policy?.remedy ? <p className="mt-1">{policy.remedy}</p> : null}
        </div>
      ) : null}
    </ChapterFrame>
  );
}
