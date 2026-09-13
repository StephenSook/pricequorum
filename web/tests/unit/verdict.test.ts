import { describe, expect, it } from "vitest";

import type { ChainVerification } from "@/lib/verify/chain";
import { verdictOf } from "@/lib/verify/verdict";

const HEAD = "a".repeat(64);

function result(overrides: Partial<ChainVerification>): ChainVerification {
  return {
    entries: 3,
    chainIntact: true,
    firstBadId: null,
    rows: [],
    computedHead: HEAD,
    headMatches: true,
    signatureValid: true,
    problems: [],
    ...overrides,
  };
}

describe("verdictOf", () => {
  it("is trusted only with an intact chain, a matching head and a valid signature", () => {
    expect(verdictOf(result({}), HEAD)).toEqual({ tone: "trusted", text: "Chain intact: 3 entries recomputed in this browser, head signature valid." });
  });

  it("does not call an unsigned chain trusted", () => {
    const verdict = verdictOf(result({ signatureValid: null }), HEAD);
    expect(verdict.tone).toBe("caution");
    expect(verdict.text).toContain("not signed");
  });

  it("fails on tampering, a mismatched or missing head, or a bad signature", () => {
    expect(verdictOf(result({ chainIntact: false, firstBadId: 2 }), HEAD)).toEqual({ tone: "failed", text: "Tampering detected at entry 2." });
    expect(verdictOf(result({ headMatches: false }), "b".repeat(64)).tone).toBe("failed");
    expect(verdictOf(result({ headMatches: false }), null).tone).toBe("failed");
    expect(verdictOf(result({ signatureValid: false }), HEAD).tone).toBe("failed");
    expect(verdictOf(result({ chainIntact: false, problems: ["The genesis value is not 32 bytes of hex."] }), HEAD).tone).toBe("failed");
  });

  it("says an empty ledger has nothing to check instead of reporting a mismatch", () => {
    expect(verdictOf(result({ entries: 0, headMatches: false, signatureValid: null }), null).tone).toBe("caution");
  });
});
