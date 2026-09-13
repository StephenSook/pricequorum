"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { useRef, type ReactNode } from "react";

import { prefersReducedMotion } from "@/lib/motion/prefersReducedMotion";

gsap.registerPlugin(useGSAP);

const TONES = {
  olive: "#465016",
  bordeaux: "#764b41",
  brown: "#594d40",
  forest: "#23280b",
} as const;

type Props = {
  index: number;
  title: string;
  tone: keyof typeof TONES;
  children: ReactNode;
  aside?: ReactNode;
};

/**
 * A sheet of ledger paper for one step of the run. It mounts only when the backend has
 * reported that step, so its entrance is the visible signal that something real happened.
 */
export function ChapterFrame({ index, title, tone, children, aside }: Props) {
  const root = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      if (prefersReducedMotion()) return;
      gsap.from(root.current, { yPercent: 10, rotation: -1.2, autoAlpha: 0, duration: 0.8, ease: "power3.out" });
      gsap.from("[data-ribbon]", { scaleX: 0, transformOrigin: "0% 50%", duration: 1, ease: "expo.out", delay: 0.15 });
    },
    { scope: root },
  );

  return (
    <section
      ref={root}
      aria-labelledby={`chapter-${index}`}
      className="texture-paper relative w-full max-w-[1040px] overflow-hidden rounded-[10px] text-ink shadow-[0_30px_60px_-30px_rgb(0_0_0/0.65)]"
    >
      <div data-ribbon aria-hidden="true" className="h-3 w-full" style={{ backgroundColor: TONES[tone] }} />
      <div className="grid gap-6 px-6 py-7 sm:px-10 sm:py-9 lg:grid-cols-[minmax(0,1fr)_280px]">
        <header className="flex items-baseline gap-4 lg:col-span-2">
          <span className="type-display text-4xl text-olive [text-shadow:none]">{String(index).padStart(2, "0")}</span>
          <h2
            id={`chapter-${index}`}
            className="type-display text-[clamp(1.6rem,3.2vw,2.4rem)] uppercase text-ink [text-shadow:0.04em_0.05em_0_rgb(217_205_173)]"
          >
            {title}
          </h2>
        </header>
        <div className="min-w-0">{children}</div>
        {aside ? <aside className="min-w-0">{aside}</aside> : null}
      </div>
    </section>
  );
}
