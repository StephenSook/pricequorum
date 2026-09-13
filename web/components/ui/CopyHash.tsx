"use client";

import { useState } from "react";

import { truncateHash } from "@/lib/format";

type CopyState = "idle" | "copied" | "blocked";

/** A truncated hash that copies its full value. The full value is always in the title. */
export function CopyHash({ value, label }: { value: string | null; label: string }) {
  const [state, setState] = useState<CopyState>("idle");

  if (!value) {
    return <span className="type-hash text-sm text-ink-soft">not reported</span>;
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      setState("blocked");
    }
    setTimeout(() => setState("idle"), 1600);
  };

  return (
    <button
      type="button"
      title={value}
      aria-label={`Copy ${label}`}
      onClick={copy}
      className="type-hash inline-flex cursor-pointer items-center gap-2 rounded px-1.5 py-0.5 text-sm text-ink transition-colors duration-200 hover:bg-olive/10"
    >
      <span>{truncateHash(value)}</span>
      <span className="text-xs text-ink-soft">
        {state === "copied" ? "copied" : state === "blocked" ? "select to copy" : "copy"}
      </span>
    </button>
  );
}
