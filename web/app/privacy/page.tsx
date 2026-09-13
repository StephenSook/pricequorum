import type { Metadata } from "next";

import { RoughFrame } from "@/components/motion/RoughFrame";
import { SceneBackdrop } from "@/components/motion/SceneBackdrop";

export const metadata: Metadata = {
  title: "Privacy | PriceQuorum",
  description: "What the PriceQuorum web and mobile apps collect and where your data goes.",
};

const REPO_ISSUES = "https://github.com/StephenSook/pricequorum/issues";

export default function PrivacyPage() {
  return (
    <main className="relative flex min-h-svh flex-1 justify-center overflow-hidden px-4 py-20">
      <SceneBackdrop dim="strong" />
      <RoughFrame />

      <article className="texture-paper relative z-[var(--z-content)] h-fit w-full max-w-[760px] rounded-[10px] px-6 py-8 text-ink shadow-[0_30px_60px_-30px_rgb(0_0_0/0.65)] sm:px-10">
        <h1 className="type-display text-[clamp(1.8rem,4vw,3rem)] uppercase text-ink [text-shadow:0.04em_0.05em_0_rgb(217_205_173)]">
          Privacy
        </h1>
        <div className="mt-4 max-w-[64ch] space-y-4 leading-relaxed text-ink-soft">
          <p>
            PriceQuorum is a hackathon project that changes a SaaS plan price across Stripe, Notion and Airtable after a
            human approves it in Slack. This page covers the web app at pricequorum-web.vercel.app and the PriceQuorum iOS
            and Android apps.
          </p>
          <h2 className="pt-2 text-lg font-semibold text-ink">What the apps collect</h2>
          <p>
            Nothing about you. There are no accounts, no analytics, no advertising and no tracking. The apps do not ask for
            your name, email, location, contacts or photos.
          </p>
          <h2 className="pt-2 text-lg font-semibold text-ink">What the apps send</h2>
          <p>
            When you start a price change, the text you type is sent to the PriceQuorum backend you use, which records the
            run and its ledger. The apps also read run events, the ledger export and evaluation results from that backend.
            They send nothing anywhere else.
          </p>
          <h2 className="pt-2 text-lg font-semibold text-ink">What stays on your device</h2>
          <p>
            The mobile app remembers the backend address you enter in Settings, on your device only. The ledger check runs
            on your device and its result is not sent back.
          </p>
          <h2 className="pt-2 text-lg font-semibold text-ink">Questions</h2>
          <p>
            Open an issue at{" "}
            <a href={REPO_ISSUES} className="font-semibold text-ink underline decoration-olive/40 underline-offset-4 hover:decoration-olive">
              github.com/StephenSook/pricequorum/issues
            </a>
            .
          </p>
          <p className="text-sm">Last updated September 13, 2026.</p>
        </div>
      </article>
    </main>
  );
}
