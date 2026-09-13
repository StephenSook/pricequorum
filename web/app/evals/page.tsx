import type { Metadata } from "next";

import { RoughFrame } from "@/components/motion/RoughFrame";
import { SceneBackdrop } from "@/components/motion/SceneBackdrop";
import { ProofBoard } from "@/components/proof/ProofBoard";

export const metadata: Metadata = {
  title: "Evaluation results | PriceQuorum",
  description: "Scenario pass rate with its confidence interval, refusals, duplicate writes prevented and every named failure.",
};

export default function EvalsPage() {
  return (
    <main className="relative flex min-h-svh flex-1 justify-center overflow-hidden px-4 py-20">
      <SceneBackdrop dim="strong" />
      <RoughFrame />
      <ProofBoard />
    </main>
  );
}
