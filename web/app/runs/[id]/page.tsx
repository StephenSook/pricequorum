import type { Metadata } from "next";

import { RoughFrame } from "@/components/motion/RoughFrame";
import { SceneBackdrop } from "@/components/motion/SceneBackdrop";
import { RunStage } from "@/components/RunStage";
import { SoundControls } from "@/components/sound/SoundControls";

export const metadata: Metadata = {
  title: "Run receipt | PriceQuorum",
  description: "Every step of one PriceQuorum price change, replayed from the events the backend recorded.",
};

const RUN_ID = /^[A-Za-z0-9-]{8,64}$/;

export default async function RunPage(props: PageProps<"/runs/[id]">) {
  const { id } = await props.params;

  return (
    <main className="relative flex min-h-svh flex-1 justify-center overflow-hidden py-10">
      <SceneBackdrop dim="strong" />
      <RoughFrame />
      {RUN_ID.test(id) ? (
        <>
          <RunStage runId={id} />
          <SoundControls />
        </>
      ) : (
        <p
          role="alert"
          className="relative z-[var(--z-content)] mx-4 mt-24 h-fit max-w-xl rounded-lg bg-forest/90 px-6 py-5 text-center text-paper-light"
        >
          That is not a valid run id. Run ids are letters, digits and hyphens.
        </p>
      )}
    </main>
  );
}
