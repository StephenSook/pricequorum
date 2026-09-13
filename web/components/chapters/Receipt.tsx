"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { useRef } from "react";

import { ChapterFrame } from "@/components/chapters/ChapterFrame";
import { CopyHash } from "@/components/ui/CopyHash";
import type { Outcome, RunView } from "@/lib/api/events";
import { prefersReducedMotion } from "@/lib/motion/prefersReducedMotion";

gsap.registerPlugin(useGSAP);

const STAMP: Record<Outcome, { label: string; color: string; meaning: string }> = {
  SUCCESS: { label: "Verified", color: "var(--color-outcome-success)", meaning: "Every app was read back and agrees." },
  PARTIAL: { label: "Partial", color: "var(--color-outcome-partial)", meaning: "Some writes landed and some did not. The ledger names which." },
  REFUSED: { label: "Refused", color: "var(--color-outcome-refused)", meaning: "A rule blocked this change." },
  NEEDS_HUMAN: { label: "Needs a person", color: "var(--color-outcome-needs-human)", meaning: "PriceQuorum would not guess." },
};

export function Receipt({ view }: { view: RunView }) {
  const stamp = useRef<HTMLDivElement>(null);
  const outcome = view.outcome;
  const style = outcome?.outcome ? STAMP[outcome.outcome] : null;

  // The one loud moment of the run: the outcome stamp lands.
  useGSAP(
    () => {
      if (!stamp.current || prefersReducedMotion()) return;
      gsap.fromTo(
        stamp.current,
        { scale: 1.8, rotation: -14, autoAlpha: 0 },
        { scale: 1, rotation: -6, autoAlpha: 1, duration: 0.45, ease: "power4.in", delay: 0.35 },
      );
    },
    { dependencies: [outcome?.outcome] },
  );

  return (
    <ChapterFrame index={5} title="The receipt" tone="olive">
      <div className="grid items-center gap-8 md:grid-cols-[auto_minmax(0,1fr)]">
        <div
          ref={stamp}
          className="type-display mx-auto rounded-md border-[6px] px-6 py-4 text-center text-[clamp(1.8rem,4vw,3rem)] uppercase [text-shadow:none]"
          style={{
            color: style?.color ?? "var(--color-ink-soft)",
            borderColor: style?.color ?? "var(--color-ink-soft)",
            filter: "url(#pq-rough-edge)",
            rotate: "-6deg",
          }}
        >
          {style?.label ?? "Unknown outcome"}
        </div>

        <div>
          <p className="text-lg font-semibold">{style?.meaning ?? "The backend reported an outcome this page does not recognise."}</p>
          {outcome?.remedy ? (
            <p className="mt-2">
              <span className="text-ink-soft">What would allow it: </span>
              {outcome.remedy}
            </p>
          ) : null}

          <dl className="mt-5 space-y-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <dt className="w-28 text-ink-soft">Ledger head</dt>
              <dd>
                <CopyHash value={outcome?.chainHead ?? null} label="ledger head hash" />
              </dd>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <dt className="w-28 text-ink-soft">Signature</dt>
              <dd>
                <CopyHash value={outcome?.signature ?? null} label="Ed25519 signature" />
              </dd>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <dt className="w-28 text-ink-soft">Public key</dt>
              <dd>
                <CopyHash value={outcome?.publicKey ?? null} label="ledger public key" />
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </ChapterFrame>
  );
}
