"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { useEffect, useRef, useState } from "react";

import { prefersReducedMotion } from "@/lib/motion/prefersReducedMotion";

gsap.registerPlugin(useGSAP);

const MIN_VISIBLE_MS = 2000;
const SQUARES = ["#616a37", "#d9cdad", "#23280b", "#616a37", "#d9cdad", "#23280b"];
const WORDMARK = "PriceQuorum";

type Props = {
  /** True once fonts, textures and the backend warm-up call have settled. */
  ready: boolean;
  onGone: () => void;
};

function Ribbon({ side }: { side: "top" | "bottom" }) {
  const squares = [...SQUARES, ...SQUARES, ...SQUARES];
  return (
    <div
      aria-hidden="true"
      className={side === "top" ? "absolute inset-x-0 top-0 h-[82px]" : "absolute inset-x-0 bottom-0 h-[82px]"}
      style={{ rotate: side === "top" ? "2deg" : "-3deg" }}
    >
      <div data-ribbon={side} className="h-full w-full overflow-hidden">
        <div className="marquee-track flex h-full w-max">
          {[0, 1].map((copy) => (
            <div key={copy} className="flex h-full items-center gap-[42px] px-6">
              {squares.map((color, i) => (
                <span key={`${copy}-${i}`} className="block h-[82px] w-12 shrink-0" style={{ backgroundColor: color }} />
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function Preloader({ ready, onGone }: Props) {
  const root = useRef<HTMLElement>(null);
  const [minElapsed, setMinElapsed] = useState(false);
  const [entered, setEntered] = useState(false);
  const leaving = useRef(false);

  useEffect(() => {
    const timer = setTimeout(() => setMinElapsed(true), MIN_VISIBLE_MS);
    return () => clearTimeout(timer);
  }, []);

  useGSAP(
    () => {
      const q = gsap.utils.selector(root);
      if (prefersReducedMotion()) {
        gsap.set(q("[data-mark]"), { clipPath: "inset(0 0% 0 0)" });
        setEntered(true);
        return;
      }
      gsap
        .timeline({ onComplete: () => setEntered(true) })
        .set(q("[data-mark]"), { clipPath: "inset(0 100% 0 0)" })
        .set(q("[data-ribbon='top']"), { xPercent: -100 })
        .set(q("[data-ribbon='bottom']"), { xPercent: 100 })
        .to(q("[data-mark]"), { clipPath: "inset(0 0% 0 0)", duration: 0.45, ease: "expo.inOut" })
        .to(q("[data-ribbon]"), { xPercent: 0, duration: 0.55, ease: "expo.inOut", stagger: 0.04 }, "-=0.12")
        .fromTo(
          q("[data-letter]"),
          { scaleY: 0.35, yPercent: 35 },
          { scaleY: 1, yPercent: 0, duration: 0.55, ease: "back.out(3)", stagger: 0.035 },
          "-=0.35",
        );
    },
    { scope: root },
  );

  useGSAP(
    () => {
      if (!ready || !minElapsed || !entered || leaving.current) return;
      leaving.current = true;
      gsap.to(root.current, {
        yPercent: -100,
        duration: prefersReducedMotion() ? 0.2 : 0.62,
        ease: "expo.inOut",
        onComplete: () => {
          gsap.set(root.current, { autoAlpha: 0 });
          onGone();
        },
      });
    },
    { scope: root, dependencies: [ready, minElapsed, entered] },
  );

  return (
    <section
      ref={root}
      role="status"
      aria-label="Loading PriceQuorum"
      className="fixed inset-0 z-[var(--z-preloader)] flex items-center justify-center overflow-hidden bg-olive"
    >
      <Ribbon side="top" />
      <div data-mark className="flex flex-col items-center gap-3 px-6">
        <p className="type-display text-[clamp(2.75rem,9vw,7rem)] text-paper-light" aria-hidden="true">
          {WORDMARK.split("").map((letter, i) => (
            <span key={i} data-letter className="inline-block origin-bottom">
              {letter}
            </span>
          ))}
        </p>
        <p className="type-kicker text-sm text-paper-deep">loading</p>
      </div>
      <Ribbon side="bottom" />
    </section>
  );
}
