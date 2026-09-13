"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { useRef, useState, type FormEvent } from "react";

import { CtaButton } from "@/components/ui/CtaButton";
import { prefersReducedMotion } from "@/lib/motion/prefersReducedMotion";

gsap.registerPlugin(useGSAP);

const ENTER = 0.85;
const APPS = ["Stripe", "Notion", "Airtable", "Slack"] as const;

type Props = {
  /** The preloader has fully left the screen. The ticket only drops in after this. */
  active: boolean;
  /** The backend accepted the run. The ticket tears away only after this. */
  leaving: boolean;
  submitting: boolean;
  error: { message: string; remedy: string | null } | null;
  onSubmit: (requestText: string) => void;
  onExited: () => void;
};

export function Ticket({ active, leaving, submitting, error, onSubmit, onExited }: Props) {
  const scope = useRef<HTMLDivElement>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const stub = useRef<HTMLDivElement>(null);
  const texture = useRef<HTMLDivElement>(null);
  const cta = useRef<HTMLDivElement>(null);
  const entered = useRef(false);
  const exited = useRef(false);
  const [request, setRequest] = useState("Raise Pro to $25 per month");

  // Hidden pre-entrance state, applied before first paint so the ticket never flashes in place.
  useGSAP(
    () => {
      if (prefersReducedMotion()) return;
      const q = gsap.utils.selector(scope);
      gsap.set(wrapper.current, { yPercent: -200, rotation: -6, scale: 0.92, transformOrigin: "50% 0%" });
      gsap.set(texture.current, { scale: 1.35, rotation: 4 });
      gsap.set(cta.current, { opacity: 0, pointerEvents: "none" });
      gsap.set(q("[data-reveal]"), { autoAlpha: 0, y: 14 });
      gsap.set(q("[data-word]"), { yPercent: 110 });
    },
    { scope },
  );

  // Entrance: ticket drops, texture settles, words slide up, CTA appears once it has landed.
  useGSAP(
    () => {
      if (!active || entered.current) return;
      entered.current = true;
      const q = gsap.utils.selector(scope);
      if (prefersReducedMotion()) {
        gsap.set([wrapper.current, texture.current, cta.current, ...q("[data-reveal]"), ...q("[data-word]")], {
          clearProps: "all",
        });
        return;
      }
      gsap
        .timeline()
        .to(wrapper.current, { yPercent: 0, rotation: 0, scale: 1, duration: ENTER, ease: "power3.out" }, 0)
        .to(texture.current, { scale: 1, rotation: -2, duration: ENTER, ease: "power2.out" }, ENTER * 0.2)
        .to(q("[data-reveal], [data-word]"), { autoAlpha: 1, y: 0, yPercent: 0, duration: 0.7, ease: "power3.out", stagger: 0.14 }, 0.2)
        .to(cta.current, { opacity: 1, pointerEvents: "auto", duration: 0.35, ease: "power2.out" }, ENTER * 0.8)
        .to(q("[data-word]"), {
          x: "random(-3, 3)",
          y: "random(-2, 2)",
          rotation: "random(-0.6, 0.6)",
          duration: 3.2,
          ease: "sine.inOut",
          yoyo: true,
          repeat: -1,
        });

      // Pointer parallax: the ticket leans toward the pointer, the texture counters it.
      const moveX = gsap.quickTo(wrapper.current, "x", { duration: 0.6, ease: "power2.out" });
      const moveY = gsap.quickTo(wrapper.current, "y", { duration: 0.6, ease: "power2.out" });
      const texX = gsap.quickTo(texture.current, "x", { duration: 0.8, ease: "power2.out" });
      const texY = gsap.quickTo(texture.current, "y", { duration: 0.8, ease: "power2.out" });
      const onMove = (event: PointerEvent) => {
        const nx = event.clientX / window.innerWidth - 0.5;
        const ny = event.clientY / window.innerHeight - 0.5;
        moveX(nx * 14);
        moveY(ny * 10);
        texX(nx * -7);
        texY(ny * -5);
      };
      window.addEventListener("pointermove", onMove);
      return () => window.removeEventListener("pointermove", onMove);
    },
    { scope, dependencies: [active] },
  );

  // Exit: the stub tears, the ticket falls away, then the chapters take over.
  useGSAP(
    () => {
      if (!leaving || exited.current) return;
      exited.current = true;
      if (prefersReducedMotion()) {
        onExited();
        return;
      }
      const pieces = [body.current, stub.current];
      gsap.killTweensOf([wrapper.current, texture.current, ...pieces]);
      gsap
        .timeline({ onComplete: onExited })
        .to(cta.current, { opacity: 0, y: 10, duration: 0.18, ease: "power2.in" }, 0)
        .to(stub.current, { rotation: 18, transformOrigin: "0% 50%", duration: 0.25, ease: "power2.in" }, 0)
        .to(
          pieces,
          {
            keyframes: [
              { x: -4, y: 6, rotation: -1, duration: 0.18, ease: "power1.out" },
              { x: "-12vw", y: "95vh", rotation: -14, scale: 0.94, duration: 0.65, ease: "power2.in" },
            ],
          },
          0.1,
        )
        .to(
          texture.current,
          {
            keyframes: [
              { x: -4, y: 6, duration: 0.18, ease: "power1.out" },
              { x: "-12vw", y: "95vh", rotation: -12, scale: 0.94, duration: 0.65, ease: "power2.in" },
            ],
          },
          0.18,
        );
    },
    { scope, dependencies: [leaving] },
  );

  const hoverStart = () => {
    if (prefersReducedMotion() || submitting) return;
    gsap.to(stub.current, { rotation: 9, transformOrigin: "0% 50%", duration: 0.7, ease: "power1.inOut", overwrite: "auto" });
    gsap.to(body.current, { x: -3, duration: 0.7, ease: "power1.inOut", overwrite: "auto" });
  };
  const hoverEnd = () => {
    if (prefersReducedMotion()) return;
    gsap.to(stub.current, { rotation: 0, duration: 0.55, ease: "power1.inOut", overwrite: "auto" });
    gsap.to(body.current, { x: 0, duration: 0.4, ease: "power2.out", overwrite: "auto" });
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = request.trim();
    if (!text || submitting) return;
    onSubmit(text);
  };

  return (
    <div ref={scope} className="relative z-[var(--z-content)] flex w-full flex-col items-center gap-7 px-4">
      <div ref={wrapper} className="relative w-full max-w-[1040px]">
        <div
          ref={texture}
          aria-hidden="true"
          className="ticket-notched absolute -left-5 -top-5 h-full w-full bg-[url(/textures/marbled-endpaper.webp)] bg-cover bg-center"
          style={{ rotate: "-1.4deg" }}
        />

        <div className="relative flex flex-col sm:flex-row">
          <div
            ref={body}
            className="ticket-notched ticket-stripes relative flex-1 bg-olive px-6 pb-9 pt-10 text-paper-light sm:px-14 sm:pb-11 sm:pt-12"
          >
            <p data-reveal className="type-kicker text-center text-sm text-paper-deep">
              one price
            </p>
            <h1 className="type-display mx-auto mt-3 flex w-fit flex-col text-[clamp(2.6rem,8.5vw,7rem)] uppercase">
              <span className="block overflow-hidden pb-[0.12em]">
                <span data-word className="block" style={{ rotate: "-2deg" }}>
                  Three
                </span>
              </span>
              <span className="block self-end overflow-hidden pb-[0.12em] pl-[0.5em]">
                <span data-word className="block">
                  systems
                </span>
              </span>
            </h1>
            <p data-reveal className="type-kicker text-center text-sm text-paper-deep">
              agree
            </p>
            <p data-reveal className="mx-auto mt-6 max-w-[54ch] text-center text-base leading-relaxed text-paper/90">
              Ask for a price change in plain words. PriceQuorum waits for approval in Slack, changes Stripe, Notion
              and Airtable exactly once, then reads all three back before it calls the job done.
            </p>

            <form id="pq-request" data-reveal onSubmit={handleSubmit} className="mx-auto mt-7 w-full max-w-[520px]">
              <label htmlFor="pq-request-text" className="block text-sm font-semibold text-paper-deep">
                Price change
              </label>
              <input
                id="pq-request-text"
                name="request_text"
                value={request}
                onChange={(event) => setRequest(event.target.value)}
                maxLength={500}
                autoComplete="off"
                spellCheck={false}
                disabled={submitting}
                className="mt-2 w-full rounded-md border border-paper/30 bg-forest/60 px-4 py-3 text-lg text-paper-light placeholder:text-paper/50 focus:border-brass disabled:opacity-60"
              />
            </form>
          </div>

          <div
            ref={stub}
            className="ticket-notched relative flex items-center justify-center border-t-2 border-dashed border-paper/30 bg-olive px-6 py-4 sm:w-[12%] sm:border-l-2 sm:border-t-0 sm:px-2"
          >
            <ul aria-label="Connected apps" className="flex gap-4 text-sm font-semibold text-paper-deep sm:flex-col sm:gap-6 sm:[writing-mode:vertical-rl]">
              {APPS.map((app) => (
                <li key={app}>{app}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <div ref={cta} className="flex flex-col items-center gap-3">
        <CtaButton type="submit" form="pq-request" disabled={submitting} onMouseEnter={hoverStart} onMouseLeave={hoverEnd}>
          {submitting ? "Starting the run" : "Start the run"}
        </CtaButton>
        {error ? (
          <div role="alert" className="max-w-[46ch] rounded-md bg-forest/85 px-4 py-3 text-center text-sm text-paper-light">
            <p className="font-semibold">{error.message}</p>
            {error.remedy ? <p className="mt-1 text-paper-deep">{error.remedy}</p> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
