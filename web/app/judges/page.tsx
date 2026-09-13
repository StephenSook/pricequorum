import type { Metadata } from "next";

import { JudgeTour } from "@/components/JudgeTour";
import { RoughFrame } from "@/components/motion/RoughFrame";
import { SceneBackdrop } from "@/components/motion/SceneBackdrop";

export const metadata: Metadata = {
  title: "Judge tour | PriceQuorum",
  description: "A three-minute path through PriceQuorum, with the state of every surface stated plainly.",
};

export default function JudgesPage() {
  return (
    <main className="relative flex min-h-svh flex-1 justify-center overflow-hidden px-4 py-20">
      <SceneBackdrop dim="strong" />
      <RoughFrame />

      <article className="texture-paper relative z-[var(--z-content)] h-fit w-full max-w-[880px] rounded-[10px] px-6 py-8 text-ink shadow-[0_30px_60px_-30px_rgb(0_0_0/0.65)] sm:px-10">
        <h1 className="type-display text-[clamp(1.8rem,4vw,3rem)] uppercase text-ink [text-shadow:0.04em_0.05em_0_rgb(217_205_173)]">
          A three-minute tour
        </h1>
        <p className="mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
          Each stop says whether it works right now for a visitor with no accounts or keys. A stop that needs the backend
          is marked live only after this browser reaches it.
        </p>
        <JudgeTour />
      </article>
    </main>
  );
}
