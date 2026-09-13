/**
 * Hermes has no WebCrypto, so the shared ledger verifier gets its hashes from @noble/hashes:
 * SHA-256 through a SubtleCrypto-shaped object passed to verifyLedger, and SHA-512 through the
 * hooks @noble/ed25519 documents for React Native. Import this module before verifying.
 */
import * as ed from "@noble/ed25519";
import { sha256, sha512 } from "@noble/hashes/sha2.js";

ed.hashes.sha512 = sha512;
ed.hashes.sha512Async = (message: Uint8Array) => Promise.resolve(sha512(message));

function toBytes(data: BufferSource): Uint8Array {
  if (data instanceof Uint8Array) return data;
  if (ArrayBuffer.isView(data)) return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  return new Uint8Array(data);
}

/** Implements only `digest("SHA-256", bytes)`, the one call verifyLedger makes. */
export const subtle = {
  async digest(algorithm: AlgorithmIdentifier, data: BufferSource): Promise<ArrayBuffer> {
    const name = typeof algorithm === "string" ? algorithm : algorithm.name;
    if (name.toUpperCase() !== "SHA-256") throw new Error(`The ${name} digest is not available in this app.`);
    const digest = sha256(toBytes(data));
    return digest.buffer.slice(digest.byteOffset, digest.byteOffset + digest.byteLength) as ArrayBuffer;
  },
} as unknown as SubtleCrypto;
