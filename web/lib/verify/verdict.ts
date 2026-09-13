import type { ChainVerification } from "@/lib/verify/chain";

export type VerdictTone = "trusted" | "caution" | "failed";

/**
 * The sentence the ledger page shows for a verification. It is green only when every entry
 * recomputes, the published head matches, and a signature over that head verifies.
 */
export function verdictOf(result: ChainVerification, publishedHead: string | null): { tone: VerdictTone; text: string } {
  const entries = `${result.entries} ${result.entries === 1 ? "entry" : "entries"}`;
  if (result.entries === 0 && result.problems.length === 0 && (publishedHead === null || result.headMatches)) {
    return { tone: "caution", text: "The ledger has no entries yet, so there is nothing to recompute." };
  }
  if (result.firstBadId !== null) return { tone: "failed", text: `Tampering detected at entry ${result.firstBadId}.` };
  if (publishedHead === null) {
    return { tone: "failed", text: "The export publishes no head, so the chain cannot be tied to a signature." };
  }
  if (!result.headMatches) return { tone: "failed", text: "The published head does not match the recomputed chain." };
  if (result.signatureValid === false) return { tone: "failed", text: "The head signature does not verify." };
  if (!result.chainIntact) return { tone: "failed", text: "The export has problems, listed below." };
  if (result.signatureValid === null) {
    return {
      tone: "caution",
      text: `All ${entries} recompute and match the published head, but the head is not signed, so a rewrite of the whole chain would not be detected.`,
    };
  }
  return { tone: "trusted", text: `Chain intact: ${entries} recomputed in this browser, head signature valid.` };
}
