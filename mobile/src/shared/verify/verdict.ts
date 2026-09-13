// GENERATED from web/lib/verify/verdict.ts by mobile/scripts/sync-shared.mjs.
// Do not edit this copy. Change the web file, then run: npm run sync

import type { ChainVerification } from "./chain";

export type VerdictTone = "trusted" | "caution" | "failed";

/**
 * The sentence the ledger page shows for a verification. It is green only when every entry
 * recomputes, the published head matches, and a signature over that head verifies. Failures are
 * checked before any caution, so an empty or unsigned ledger can never hide a bad signature.
 */
export function verdictOf(result: ChainVerification, publishedHead: string | null): { tone: VerdictTone; text: string } {
  const entries = `${result.entries} ${result.entries === 1 ? "entry" : "entries"}`;
  if (result.firstBadId !== null) return { tone: "failed", text: `Tampering detected at entry ${result.firstBadId}.` };
  if (result.signatureValid === false) return { tone: "failed", text: "The head signature does not verify." };
  if (!result.chainIntact) return { tone: "failed", text: "The export has problems, listed below." };
  if (result.entries === 0 && (publishedHead === null || result.headMatches)) {
    return { tone: "caution", text: "The ledger has no entries yet, so there is nothing to recompute." };
  }
  if (publishedHead === null) {
    return { tone: "failed", text: "The export publishes no head, so the chain cannot be tied to a signature." };
  }
  if (!result.headMatches) return { tone: "failed", text: "The published head does not match the recomputed chain." };
  if (result.signatureValid === null) {
    return {
      tone: "caution",
      text: `All ${entries} recompute and match the published head, but the head is not signed, so a rewrite of the whole chain would not be detected.`,
    };
  }
  return { tone: "trusted", text: `Chain intact: ${entries} recomputed in this browser, head signature valid.` };
}
