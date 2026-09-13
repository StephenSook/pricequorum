// GENERATED from web/lib/verify/chain.ts by mobile/scripts/sync-shared.mjs.
// Do not edit this copy. Change the web file, then run: npm run sync

/**
 * Browser-side ledger verification.
 *
 * Recomputes the hash chain from the published ledger export and checks the Ed25519
 * signature on its head, so a visitor does not have to trust the server's own verdict.
 *
 * Chain rule (docs/contracts/api.md):
 *   entry_hash = sha256(bytes(prev_hash) || utf8(RFC8785(payload)))
 *   the first prev_hash is 32 zero bytes; the signature is Ed25519 over bytes(head).
 */
import { etc, verifyAsync } from "@noble/ed25519";
import canonicalize from "canonicalize";

export const GENESIS_HEX = "0".repeat(64);

const HEX_64 = /^[0-9a-f]{64}$/;
const HEX_128 = /^[0-9a-f]{128}$/;

export type ExportRow = { id: number; prevHash: string; entryHash: string; payload: unknown };

export type LedgerExport = {
  algorithm: { hash: string; canonicalization: string; signature: string };
  genesis: string;
  rows: ExportRow[];
  head: string | null;
  signature: string | null;
  publicKey: string | null;
};

export type RowResult = { id: number; ok: boolean; prevLinkOk: boolean; expected: string | null; got: string };

export type ChainVerification = {
  entries: number;
  chainIntact: boolean;
  firstBadId: number | null;
  rows: RowResult[];
  computedHead: string;
  headMatches: boolean;
  /** null when the export carries no signature or no public key to check against. */
  signatureValid: boolean | null;
  problems: string[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function lowerHexOrNull(value: unknown): string | null {
  return typeof value === "string" ? value.toLowerCase() : null;
}

/**
 * Validates the raw JSON from GET /api/ledger/export. Returns the parsed export, or a list
 * of reasons it cannot be verified. Nothing missing is filled in.
 */
export function parseLedgerExport(body: unknown): { ok: true; value: LedgerExport } | { ok: false; reasons: string[] } {
  const reasons: string[] = [];
  if (!isRecord(body)) return { ok: false, reasons: ["The export is not a JSON object."] };

  const algorithm = isRecord(body.algorithm) ? body.algorithm : {};
  const hash = typeof algorithm.hash === "string" ? algorithm.hash : "";
  const canonicalization = typeof algorithm.canonicalization === "string" ? algorithm.canonicalization : "";
  const signature = typeof algorithm.signature === "string" ? algorithm.signature : "";
  if (hash.toLowerCase() !== "sha256") reasons.push(`Unsupported hash "${hash}". This page verifies sha256 only.`);
  if (canonicalization.toUpperCase() !== "RFC8785") reasons.push(`Unsupported canonicalization "${canonicalization}".`);
  if (signature.toLowerCase() !== "ed25519") reasons.push(`Unsupported signature "${signature}".`);

  const genesis = lowerHexOrNull(body.genesis);
  if (genesis === null) reasons.push("The export has no genesis value.");

  if (!Array.isArray(body.rows)) reasons.push("The export has no rows array.");
  const rows: ExportRow[] = [];
  if (Array.isArray(body.rows)) {
    body.rows.forEach((row, index) => {
      if (!isRecord(row) || typeof row.id !== "number" || typeof row.prev_hash !== "string" || typeof row.entry_hash !== "string" || !("payload" in row)) {
        reasons.push(`Row at position ${index} is missing id, prev_hash, entry_hash or payload.`);
        return;
      }
      rows.push({ id: row.id, prevHash: row.prev_hash.toLowerCase(), entryHash: row.entry_hash.toLowerCase(), payload: row.payload });
    });
  }

  if (reasons.length > 0 || genesis === null) return { ok: false, reasons };
  return {
    ok: true,
    value: {
      algorithm: { hash, canonicalization, signature },
      genesis,
      rows,
      head: lowerHexOrNull(body.head),
      signature: lowerHexOrNull(body.signature),
      publicKey: lowerHexOrNull(body.public_key),
    },
  };
}

async function sha256Hex(bytes: Uint8Array, subtle: SubtleCrypto): Promise<string> {
  const digest = await subtle.digest("SHA-256", bytes as BufferSource);
  return etc.bytesToHex(new Uint8Array(digest));
}

function canonicalOrUndefined(payload: unknown): string | undefined {
  try {
    return canonicalize(payload);
  } catch {
    return undefined;
  }
}

/** Recomputes every entry hash in id order and checks the signed head. Never throws on bad data. */
export async function verifyLedger(exported: LedgerExport, subtle: SubtleCrypto = globalThis.crypto.subtle): Promise<ChainVerification> {
  const problems: string[] = [];
  const encoder = new TextEncoder();
  const rows = [...exported.rows].sort((a, b) => a.id - b.id);
  const results: RowResult[] = [];
  let firstBadId: number | null = null;

  // The contract fixes the root: a chain started from any other value is not this ledger.
  if (exported.genesis !== GENESIS_HEX) problems.push("The genesis value is not 32 zero bytes, as the chain rule requires.");
  let prev = GENESIS_HEX;

  for (const row of rows) {
    const jcs = canonicalOrUndefined(row.payload);
    if (jcs === undefined || !HEX_64.test(row.prevHash) || !HEX_64.test(row.entryHash)) {
      problems.push(`Entry ${row.id} has a payload that cannot be canonicalized or a hash that is not 32 bytes of hex.`);
      results.push({ id: row.id, ok: false, prevLinkOk: false, expected: null, got: row.entryHash });
      if (firstBadId === null) firstBadId = row.id;
      continue;
    }
    const expected = await sha256Hex(etc.concatBytes(etc.hexToBytes(prev), encoder.encode(jcs)), subtle);
    const prevLinkOk = row.prevHash === prev;
    const ok = prevLinkOk && expected === row.entryHash;
    results.push({ id: row.id, ok, prevLinkOk, expected, got: row.entryHash });
    if (!ok && firstBadId === null) firstBadId = row.id;
    prev = expected;
  }

  const computedHead = prev;
  const headMatches = exported.head !== null && exported.head === computedHead;

  let signatureValid: boolean | null = null;
  if (exported.signature && exported.publicKey && exported.head) {
    if (!HEX_128.test(exported.signature) || !HEX_64.test(exported.publicKey) || !HEX_64.test(exported.head)) {
      problems.push("The signature, public key or head is not valid hex of the expected length.");
      signatureValid = false;
    } else {
      try {
        signatureValid = await verifyAsync(
          etc.hexToBytes(exported.signature),
          etc.hexToBytes(exported.head),
          etc.hexToBytes(exported.publicKey),
        );
      } catch {
        problems.push("The signature could not be checked against the public key.");
        signatureValid = false;
      }
    }
  }

  return {
    entries: rows.length,
    chainIntact: firstBadId === null && problems.length === 0,
    firstBadId,
    rows: results,
    computedHead,
    headMatches,
    signatureValid,
    problems,
  };
}

/**
 * Returns a copy of the export with one character changed in the chosen entry's payload.
 * Used for the in-browser tamper demonstration; the server's ledger is never touched.
 */
export function tamperCopy(exported: LedgerExport, entryId: number): { copy: LedgerExport; field: string } {
  const copy: LedgerExport = JSON.parse(JSON.stringify(exported));
  const row = copy.rows.find((r) => r.id === entryId);
  if (!row) return { copy, field: "none" };
  if (isRecord(row.payload)) {
    const key = Object.keys(row.payload).find((k) => typeof (row.payload as Record<string, unknown>)[k] === "string");
    if (key) {
      const value = (row.payload as Record<string, string>)[key];
      const last = value.slice(-1);
      (row.payload as Record<string, string>)[key] = value.slice(0, -1) + (last === "x" ? "y" : "x");
      return { copy, field: key };
    }
    (row.payload as Record<string, unknown>).edited_in_browser = true;
    return { copy, field: "edited_in_browser" };
  }
  row.payload = { edited_in_browser: true, original: row.payload };
  return { copy, field: "payload" };
}
