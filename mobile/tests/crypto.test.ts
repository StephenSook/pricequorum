/**
 * Proves the on-device ledger check works without WebCrypto, as on Hermes: SHA-256 comes from the
 * shim in src/crypto.ts and SHA-512 (for Ed25519) from the @noble/ed25519 hooks it sets.
 */
import * as ed from "@noble/ed25519";
import { sha256 } from "@noble/hashes/sha2.js";
import canonicalize from "canonicalize";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { subtle } from "../src/crypto";
import { GENESIS_HEX, tamperCopy, verifyLedger, type LedgerExport } from "../src/shared/verify/chain";
import { verdictOf } from "../src/shared/verify/verdict";

const encoder = new TextEncoder();
const ALGORITHM = { hash: "sha256", canonicalization: "RFC8785", signature: "ed25519" };

const PAYLOADS = [
  { run_id: "run-1", step_no: 1, app: "stripe", action: "create_price", idempotency_key: "pq:pro:v2:create_price", state: "completed" },
  { run_id: "run-1", step_no: 2, app: "notion", action: "update_price", idempotency_key: "pq:pro:v2:notion", state: "completed" },
  { run_id: "run-1", step_no: 3, app: "airtable", action: "upsert_price", idempotency_key: "pq:pro:v2:airtable", state: "completed" },
];

// The same golden values the web verifier is tested against, computed with Python's hashlib.
const PYTHON_HASH_1 = "63c3970cfd8b8f453815573428f533ad43e6e436a7bc05dd06a0babdd7d9283e";
const PYTHON_HASH_2 = "8e5b68857070f08da16db16eae12f4eed32217ef4051de6d9810bd190c2430f3";

/** Builds a signed chain from the documented rule, independently of the verifier. */
function buildLedger(seed: string): LedgerExport {
  const secretKey = sha256(encoder.encode(seed));
  let prev = GENESIS_HEX;
  const rows = PAYLOADS.map((payload, index) => {
    const entryHash = ed.etc.bytesToHex(sha256(ed.etc.concatBytes(ed.etc.hexToBytes(prev), encoder.encode(canonicalize(payload)!))));
    const row = { id: index + 1, prevHash: prev, entryHash, payload };
    prev = entryHash;
    return row;
  });
  return {
    algorithm: ALGORITHM,
    genesis: GENESIS_HEX,
    rows,
    head: prev,
    signature: ed.etc.bytesToHex(ed.sign(ed.etc.hexToBytes(prev), secretKey)),
    publicKey: ed.etc.bytesToHex(ed.getPublicKey(secretKey)),
  };
}

describe("on-device ledger verification without WebCrypto", () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, "crypto");

  // Hermes has no WebCrypto. Remove Node's for these tests so nothing can quietly fall back to it.
  beforeAll(() => {
    Object.defineProperty(globalThis, "crypto", { value: undefined, configurable: true, writable: true });
  });
  afterAll(() => {
    if (original) Object.defineProperty(globalThis, "crypto", original);
  });

  it("runs with WebCrypto absent, as on Hermes", () => {
    expect((globalThis as { crypto?: unknown }).crypto).toBeUndefined();
  });

  it("recomputes the same entry hashes as Python's hashlib through the SHA-256 shim", async () => {
    const result = await verifyLedger(
      {
        algorithm: ALGORITHM,
        genesis: GENESIS_HEX,
        rows: [
          { id: 1, prevHash: GENESIS_HEX, entryHash: PYTHON_HASH_1, payload: PAYLOADS[0] },
          { id: 2, prevHash: PYTHON_HASH_1, entryHash: PYTHON_HASH_2, payload: PAYLOADS[1] },
        ],
        head: PYTHON_HASH_2,
        signature: null,
        publicKey: null,
      },
      subtle,
    );
    expect(result.rows.map((r) => r.expected)).toEqual([PYTHON_HASH_1, PYTHON_HASH_2]);
    expect(result.chainIntact).toBe(true);
    expect(result.headMatches).toBe(true);
  });

  it("verifies a real Ed25519 signature over the head and calls the chain trusted", async () => {
    const ledger = buildLedger("pricequorum mobile test key");
    const result = await verifyLedger(ledger, subtle);
    expect(result.signatureValid).toBe(true);
    expect(verdictOf(result, ledger.head).tone).toBe("trusted");
  });

  it("rejects a head signed by a different key", async () => {
    const ledger = buildLedger("pricequorum mobile test key");
    const otherKey = sha256(encoder.encode("some other key"));
    const forged = { ...ledger, signature: ed.etc.bytesToHex(ed.sign(ed.etc.hexToBytes(ledger.head!), otherKey)) };
    const result = await verifyLedger(forged, subtle);
    expect(result.signatureValid).toBe(false);
    expect(verdictOf(result, forged.head).tone).toBe("failed");
  });

  it("names the entry that was edited in a copy", async () => {
    const ledger = buildLedger("pricequorum mobile test key");
    const { copy } = tamperCopy(ledger, 2);
    const result = await verifyLedger(copy, subtle);
    expect(result.firstBadId).toBe(2);
    expect(verdictOf(result, copy.head).tone).toBe("failed");
  });
});
