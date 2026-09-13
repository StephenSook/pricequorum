// @vitest-environment node
import { etc, getPublicKeyAsync, signAsync, utils } from "@noble/ed25519";
import canonicalize from "canonicalize";
import { describe, expect, it } from "vitest";

import { GENESIS_HEX, parseLedgerExport, tamperCopy, verifyLedger, type LedgerExport } from "@/lib/verify/chain";

const encoder = new TextEncoder();

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as BufferSource);
  return etc.bytesToHex(new Uint8Array(digest));
}

/** Builds a real signed chain from the documented rule, independently of the verifier. */
async function buildLedger(payloads: Record<string, unknown>[]): Promise<{ ledger: LedgerExport; secretKey: Uint8Array }> {
  const secretKey = utils.randomSecretKey();
  const publicKey = await getPublicKeyAsync(secretKey);
  let prev = GENESIS_HEX;
  const rows = [];
  for (const [index, payload] of payloads.entries()) {
    const entryHash = await sha256Hex(etc.concatBytes(etc.hexToBytes(prev), encoder.encode(canonicalize(payload)!)));
    rows.push({ id: index + 1, prevHash: prev, entryHash, payload });
    prev = entryHash;
  }
  const signature = await signAsync(etc.hexToBytes(prev), secretKey);
  return {
    secretKey,
    ledger: {
      algorithm: { hash: "sha256", canonicalization: "RFC8785", signature: "ed25519" },
      genesis: GENESIS_HEX,
      rows,
      head: prev,
      signature: etc.bytesToHex(signature),
      publicKey: etc.bytesToHex(publicKey),
    },
  };
}

const PAYLOADS = [
  { run_id: "run-1", step_no: 1, app: "stripe", action: "create_price", idempotency_key: "pq:pro:v2:create_price", state: "completed" },
  { run_id: "run-1", step_no: 2, app: "notion", action: "update_price", idempotency_key: "pq:pro:v2:notion", state: "completed" },
  { run_id: "run-1", step_no: 3, app: "airtable", action: "upsert_price", idempotency_key: "pq:pro:v2:airtable", state: "completed" },
];

describe("verifyLedger", () => {
  it("accepts an intact chain with a valid signed head", async () => {
    const { ledger } = await buildLedger(PAYLOADS);
    const result = await verifyLedger(ledger);
    expect(result).toMatchObject({ entries: 3, chainIntact: true, firstBadId: null, headMatches: true, signatureValid: true });
    expect(result.problems).toEqual([]);
  });

  it("does not depend on the key order the server happened to serialise", async () => {
    const { ledger } = await buildLedger(PAYLOADS);
    const reordered = structuredClone(ledger);
    reordered.rows[1].payload = Object.fromEntries(Object.entries(reordered.rows[1].payload as object).reverse());
    expect((await verifyLedger(reordered)).chainIntact).toBe(true);
  });

  it("names the entry that was edited after it was written", async () => {
    const { ledger } = await buildLedger(PAYLOADS);
    const { copy, field } = tamperCopy(ledger, 2);
    const result = await verifyLedger(copy);
    expect(field).toBe("run_id");
    expect(result.chainIntact).toBe(false);
    expect(result.firstBadId).toBe(2);
    const row = result.rows.find((r) => r.id === 2)!;
    expect(row.ok).toBe(false);
    expect(row.expected).not.toBe(row.got);
    expect(result.headMatches).toBe(false);
  });

  it("rejects a head signed by a different key", async () => {
    const { ledger } = await buildLedger(PAYLOADS);
    const other = utils.randomSecretKey();
    const forged = { ...ledger, signature: etc.bytesToHex(await signAsync(etc.hexToBytes(ledger.head!), other)) };
    const result = await verifyLedger(forged);
    expect(result.headMatches).toBe(true);
    expect(result.signatureValid).toBe(false);
  });

  it("reports malformed hashes as problems instead of throwing", async () => {
    const { ledger } = await buildLedger(PAYLOADS);
    const broken = structuredClone(ledger);
    broken.rows[0].prevHash = "not-hex";
    const result = await verifyLedger(broken);
    expect(result.chainIntact).toBe(false);
    expect(result.firstBadId).toBe(1);
    expect(result.problems.length).toBeGreaterThan(0);
  });

  it("returns null for the signature check when no signature was published", async () => {
    const { ledger } = await buildLedger(PAYLOADS);
    const result = await verifyLedger({ ...ledger, signature: null });
    expect(result.signatureValid).toBeNull();
    expect(result.chainIntact).toBe(true);
  });
});

describe("parseLedgerExport", () => {
  it("maps the API's snake_case fields", () => {
    const parsed = parseLedgerExport({
      algorithm: { hash: "sha256", canonicalization: "RFC8785", signature: "ed25519" },
      genesis: GENESIS_HEX,
      rows: [{ id: 1, run_id: "r", prev_hash: GENESIS_HEX.toUpperCase(), entry_hash: "AB".repeat(32), payload: { a: 1 } }],
      head: "AB".repeat(32),
      signature: null,
      public_key: "CD".repeat(32),
    });
    expect(parsed.ok).toBe(true);
    if (parsed.ok) {
      expect(parsed.value.rows[0]).toEqual({ id: 1, prevHash: GENESIS_HEX, entryHash: "ab".repeat(32), payload: { a: 1 } });
      expect(parsed.value.publicKey).toBe("cd".repeat(32));
    }
  });

  it("refuses an algorithm this page does not implement", () => {
    const parsed = parseLedgerExport({ algorithm: { hash: "sha512", canonicalization: "RFC8785", signature: "ed25519" }, rows: [] });
    expect(parsed.ok).toBe(false);
  });

  it("refuses rows missing their hashes", () => {
    const parsed = parseLedgerExport({ algorithm: { hash: "sha256", canonicalization: "RFC8785", signature: "ed25519" }, rows: [{ id: 1 }] });
    expect(parsed.ok).toBe(false);
  });
});

describe("agreement with an independent implementation", () => {
  // Golden values computed with Python's hashlib and json.dumps(sort_keys=True, separators=(",", ":")),
  // which equals RFC 8785 output for ASCII keys and integer values. A shared misreading of the chain
  // rule between this verifier and its own tests would fail here.
  const PYTHON_JCS_1 =
    '{"action":"create_price","app":"stripe","idempotency_key":"pq:pro:v2:create_price","run_id":"run-1","state":"completed","step_no":1}';
  const PYTHON_HASH_1 = "63c3970cfd8b8f453815573428f533ad43e6e436a7bc05dd06a0babdd7d9283e";
  const PYTHON_HASH_2 = "8e5b68857070f08da16db16eae12f4eed32217ef4051de6d9810bd190c2430f3";

  it("canonicalizes a payload exactly as Python does, whatever the key order", () => {
    const shuffled = { state: "completed", step_no: 1, run_id: "run-1", idempotency_key: "pq:pro:v2:create_price", app: "stripe", action: "create_price" };
    expect(canonicalize(shuffled)).toBe(PYTHON_JCS_1);
  });

  it("recomputes the same entry hashes and head as Python", async () => {
    const result = await verifyLedger({
      algorithm: { hash: "sha256", canonicalization: "RFC8785", signature: "ed25519" },
      genesis: GENESIS_HEX,
      rows: [
        { id: 1, prevHash: GENESIS_HEX, entryHash: PYTHON_HASH_1, payload: PAYLOADS[0] },
        { id: 2, prevHash: PYTHON_HASH_1, entryHash: PYTHON_HASH_2, payload: PAYLOADS[1] },
      ],
      head: PYTHON_HASH_2,
      signature: null,
      publicKey: null,
    });
    expect(result.rows.map((r) => r.expected)).toEqual([PYTHON_HASH_1, PYTHON_HASH_2]);
    expect(result.computedHead).toBe(PYTHON_HASH_2);
    expect(result.chainIntact).toBe(true);
    expect(result.headMatches).toBe(true);
  });
});
