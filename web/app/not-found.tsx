import Link from "next/link";

import { RoughFrame } from "@/components/motion/RoughFrame";
import { SceneBackdrop } from "@/components/motion/SceneBackdrop";

const linkClass = "text-lg font-semibold underline decoration-olive/40 underline-offset-4 hover:decoration-olive";

export default function NotFound() {
  return (
    <main className="relative flex min-h-svh flex-1 justify-center overflow-hidden px-4 py-20">
      <SceneBackdrop dim="strong" />
      <RoughFrame />

      <article className="texture-paper relative z-[var(--z-content)] h-fit w-full max-w-[640px] rounded-[10px] px-6 py-8 text-ink shadow-[0_30px_60px_-30px_rgb(0_0_0/0.65)] sm:px-10">
        <h1 className="type-display text-[clamp(1.8rem,4vw,3rem)] uppercase text-ink [text-shadow:0.04em_0.05em_0_rgb(217_205_173)]">
          No page here
        </h1>
        <p className="mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
          This address does not match a PriceQuorum page. Check the link, or start from one of these.
        </p>
        <ul className="mt-6 space-y-3">
          <li>
            <Link href="/" className={linkClass}>
              Start a price change
            </Link>
          </li>
          <li>
            <Link href="/judges" className={linkClass}>
              Take the judge tour
            </Link>
          </li>
        </ul>
      </article>
    </main>
  );
}
