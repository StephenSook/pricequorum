import type { Metadata } from "next";

import { RoughFrame } from "@/components/motion/RoughFrame";
import { SceneBackdrop } from "@/components/motion/SceneBackdrop";
import { LedgerVerifier } from "@/components/verify/LedgerVerifier";

export const metadata: Metadata = {
  title: "Verify the ledger | PriceQuorum",
  description: "Recompute the PriceQuorum ledger hash chain and check its Ed25519 signature in your own browser.",
};

export default function VerifyPage() {
  return (
    <main className="relative flex min-h-svh flex-1 items-start justify-center overflow-hidden px-4 py-20">
      <SceneBackdrop dim="medium" />
      <RoughFrame />
      <LedgerVerifier />
    </main>
  );
}
