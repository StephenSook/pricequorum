import type { Metadata } from "next";

import { BreakPanel } from "@/components/break/BreakPanel";
import { RoughFrame } from "@/components/motion/RoughFrame";
import { SceneBackdrop } from "@/components/motion/SceneBackdrop";
import { SoundControls } from "@/components/sound/SoundControls";

export const metadata: Metadata = {
  title: "Try to break it | PriceQuorum",
  description: "Start sandbox runs that go wrong on purpose and watch how PriceQuorum handles each failure.",
};

export default function BreakPage() {
  return (
    <main className="relative flex min-h-svh flex-1 justify-center overflow-hidden px-4 py-20">
      <SceneBackdrop dim="strong" />
      <RoughFrame />
      <BreakPanel />
      <SoundControls />
    </main>
  );
}
