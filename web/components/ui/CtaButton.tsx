import clsx from "clsx";
import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: "light" | "dark";
};

/**
 * Ticket-shaped call to action: scalloped corners and punched side notches.
 * All arcs sweep inward, so the outline reads as a torn-off admission ticket.
 */
const TICKET_PATH =
  "M12 0 H188 A12 12 0 0 0 200 12 V22 A8 8 0 0 0 200 38 V48 A12 12 0 0 0 188 60 H12 A12 12 0 0 0 0 48 V38 A8 8 0 0 0 0 22 V12 A12 12 0 0 0 12 0 Z";

export function CtaButton({ tone = "light", className, children, type = "button", ...rest }: Props) {
  return (
    <button
      type={type}
      {...rest}
      className={clsx(
        "group relative inline-flex h-[60px] min-w-[220px] cursor-pointer select-none items-center justify-center px-10",
        "transition-[transform,filter,opacity] duration-300 ease-out",
        "hover:-translate-y-px hover:drop-shadow-[0_0_22px_rgb(246_240_225/0.45)]",
        "disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:translate-y-0 disabled:hover:drop-shadow-none",
        tone === "light" ? "text-forest" : "text-paper-light",
        className,
      )}
    >
      <svg
        aria-hidden="true"
        focusable="false"
        viewBox="0 0 200 60"
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full"
      >
        <path d={TICKET_PATH} className={tone === "light" ? "fill-paper-light" : "fill-forest"} />
      </svg>
      <span className="relative text-lg font-bold tracking-[-0.02em]">{children}</span>
    </button>
  );
}
