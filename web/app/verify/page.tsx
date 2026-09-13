import type { Metadata } from "next";

import { RoughFrame } from "@/components/motion/RoughFrame";
import { LedgerVerifier } from "@/components/verify/LedgerVerifier";

export const metadata: Metadata = {
  title: "Verify the ledger | PriceQuorum",
  description: "Recompute the PriceQuorum ledger hash chain and check its Ed25519 signature in your own browser.",
};

export default function VerifyPage() {
  return (
    <main className="relative flex min-h-svh flex-1 items-start justify-center overflow-hidden px-4 py-20">
      <div
        aria-hidden="true"
        className="fixed inset-0 z-[var(--z-canvas)] bg-cover bg-center"
        style={{
          backgroundImage:
            "linear-gradient(rgb(35 40 11 / 0.55), rgb(35 40 11 / 0.7)), url(/scenes/ledger-desk.webp), url(/textures/ink-paper-dark.webp)",
        }}
      />
      <RoughFrame />
      <LedgerVerifier />
    </main>
  );
}
