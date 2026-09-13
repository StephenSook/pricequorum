"""The action ledger: a pending row before every external call, a SHA-256 hash chain over RFC 8785
canonical payloads, and an Ed25519 signature over the chain head.

Chain rule (docs/contracts/api.md): entry_hash = sha256(bytes(prev_hash) || RFC8785(payload)),
starting from 32 zero bytes. Payloads contain no floats.

Signing key tradeoff: PQ_SIGNING_KEY (a hex seed) wins when it is set. Without it the key is
generated once on first boot and stored in the signing_keys table, so it survives restarts on a
host with no persistent disk and never appears in deploy config or on a laptop. The cost: anyone
with write access to the database could also read the key and re-sign a rewritten chain. Setting
PQ_SIGNING_KEY from a secret store separates the key from the data it protects.

What the chain proves, stated plainly: it detects modification of recorded history. It does not
prevent an attacker with full write access and the key from rebuilding the chain, and it carries no
trusted timestamp.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

import rfc8785
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey
from psycopg.types.json import Jsonb

from pricequorum import db

GENESIS = bytes(32)
_CHAIN_LOCK = 7_342_001

_signing_key: SigningKey | None = None


def _reject_floats(value: Any) -> None:
    if isinstance(value, float):
        raise TypeError("ledger payloads must not contain floats; use integer minor units")
    if isinstance(value, dict):
        for item in value.values():
            _reject_floats(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _reject_floats(item)


def canonical(payload: Any) -> bytes:
    _reject_floats(payload)
    return rfc8785.dumps(payload)


def compute_entry_hash(prev_hash: bytes, payload: Any) -> bytes:
    return hashlib.sha256(prev_hash + canonical(payload)).digest()


def hash_args(args: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(args)).hexdigest()


def load_signing_key(configured_hex: str | None) -> SigningKey:
    global _signing_key
    if configured_hex:
        key = SigningKey(bytes.fromhex(configured_hex.strip()))
    else:
        with db.connect() as conn, conn.transaction():
            conn.execute(
                "insert into signing_keys (id, seed_hex) values (1, %s) on conflict (id) do nothing",
                (secrets.token_hex(32),),
            )
            row = conn.execute("select seed_hex from signing_keys where id = 1").fetchone()
        assert row is not None
        key = SigningKey(bytes.fromhex(row["seed_hex"]))
    _signing_key = key
    return key


def signing_key() -> SigningKey:
    if _signing_key is None:
        raise RuntimeError("the ledger signing key has not been loaded")
    return _signing_key


def public_key_hex() -> str:
    return signing_key().verify_key.encode().hex()


def sign_head(head_hex: str) -> str:
    return signing_key().sign(bytes.fromhex(head_hex)).signature.hex()


def signature_valid(head_hex: str, signature_hex: str, public_hex: str) -> bool:
    try:
        VerifyKey(bytes.fromhex(public_hex)).verify(bytes.fromhex(head_hex), bytes.fromhex(signature_hex))
        return True
    except (BadSignatureError, ValueError):
        return False


@dataclass(frozen=True)
class LedgerRow:
    id: int
    run_id: str
    step_no: int
    app: str
    action: str
    idempotency_key: str
    args_hash: str
    state: str
    external_object_id: str | None
    chain_id: int | None
    is_new: bool


def _row(row: dict[str, Any], is_new: bool) -> LedgerRow:
    return LedgerRow(
        id=row["id"],
        run_id=str(row["run_id"]),
        step_no=row["step_no"],
        app=row["app"],
        action=row["action"],
        idempotency_key=row["idempotency_key"],
        args_hash=row["args_hash"],
        state=row["state"],
        external_object_id=row["external_object_id"],
        chain_id=row["chain_id"],
        is_new=is_new,
    )


def pending(
    run_id: str,
    step_no: int,
    app: str,
    action: str,
    idempotency_key: str,
    args: dict[str, Any],
    expected_postcondition: dict[str, Any],
) -> LedgerRow:
    """Records the intent before the external call. A key already in the ledger is returned as it
    stands; when it already completed, the duplicate write it would have caused is counted."""
    args_hash = hash_args(args)
    with db.connect() as conn, conn.transaction():
        row = conn.execute(
            """insert into action_ledger
                 (run_id, step_no, app, action, idempotency_key, args_hash, expected_postcondition)
               values (%s, %s, %s, %s, %s, %s, %s)
               on conflict (idempotency_key) do nothing
               returning *""",
            (run_id, step_no, app, action, idempotency_key, args_hash, Jsonb(expected_postcondition)),
        ).fetchone()
        if row is not None:
            return _row(row, True)
        existing = conn.execute("select * from action_ledger where idempotency_key = %s", (idempotency_key,)).fetchone()
        assert existing is not None
        if existing["state"] == "completed":
            conn.execute(
                "update action_ledger set duplicates_prevented = duplicates_prevented + 1 where id = %s",
                (existing["id"],),
            )
        return _row(existing, False)


def append_chain(run_id: str | None, payload: dict[str, Any]) -> tuple[int, str, str]:
    """Appends one entry under a transaction-scoped lock. Returns (chain id, prev hash, entry hash)."""
    with db.connect() as conn, conn.transaction():
        conn.execute("select pg_advisory_xact_lock(%s)", (_CHAIN_LOCK,))
        last = conn.execute("select entry_hash from ledger_chain order by id desc limit 1").fetchone()
        prev = bytes.fromhex(last["entry_hash"]) if last else GENESIS
        entry = compute_entry_hash(prev, payload)
        inserted = conn.execute(
            "insert into ledger_chain (run_id, payload, prev_hash, entry_hash) values (%s, %s, %s, %s) returning id",
            (run_id, Jsonb(payload), prev.hex(), entry.hex()),
        ).fetchone()
    assert inserted is not None
    return inserted["id"], prev.hex(), entry.hex()


def complete(row: LedgerRow, external_object_id: str) -> tuple[str, str]:
    """Marks the step completed and chains it. Returns (prev hash, entry hash)."""
    if row.state == "completed" and row.chain_id is not None:
        with db.connect() as conn:
            chained = conn.execute(
                "select prev_hash, entry_hash from ledger_chain where id = %s", (row.chain_id,)
            ).fetchone()
        if chained is not None:
            return chained["prev_hash"], chained["entry_hash"]
    payload = {
        "kind": "ledger_step",
        "run_id": row.run_id,
        "step_no": row.step_no,
        "app": row.app,
        "action": row.action,
        "idempotency_key": row.idempotency_key,
        "args_hash": row.args_hash,
        "external_object_id": external_object_id,
        "state": "completed",
    }
    chain_id, prev, entry = append_chain(row.run_id, payload)
    with db.connect() as conn:
        conn.execute(
            """update action_ledger set state = 'completed', external_object_id = %s, chain_id = %s,
                 completed_at = now() where id = %s""",
            (external_object_id, chain_id, row.id),
        )
    return prev, entry


def fail(row: LedgerRow, outcome: str, remedy: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "update action_ledger set state = 'failed', outcome = %s, remedy = %s where id = %s and state = 'pending'",
            (outcome, remedy, row.id),
        )


def _chain_rows() -> list[dict[str, Any]]:
    with db.connect() as conn:
        return conn.execute(
            "select id, run_id, payload, prev_hash, entry_hash from ledger_chain order by id"
        ).fetchall()


def export() -> dict[str, Any]:
    rows = _chain_rows()
    head = rows[-1]["entry_hash"] if rows else GENESIS.hex()
    return {
        "algorithm": {"hash": "sha256", "canonicalization": "RFC8785", "signature": "ed25519"},
        "genesis": GENESIS.hex(),
        "rows": [
            {
                "id": row["id"],
                "run_id": str(row["run_id"]) if row["run_id"] else None,
                "prev_hash": row["prev_hash"],
                "entry_hash": row["entry_hash"],
                "payload": row["payload"],
            }
            for row in rows
        ],
        "head": head,
        "signature": sign_head(head),
        "public_key": public_key_hex(),
    }


def recompute(rows: list[dict[str, Any]]) -> tuple[int | None, str | None, str | None]:
    """Walks rows in order from the genesis value. Returns (first bad id, expected hash, stored hash), or three
    Nones when every row matches. Pure, so it checks the stored chain and in-memory copies the same way."""
    prev = GENESIS
    for row in rows:
        recomputed = compute_entry_hash(prev, row["payload"])
        if row["prev_hash"] != prev.hex() or row["entry_hash"] != recomputed.hex():
            return int(row["id"]), recomputed.hex(), str(row["entry_hash"])
        prev = recomputed
    return None, None, None


def verify() -> dict[str, Any]:
    """Recomputes the chain from the stored payloads and checks the signature over the recomputed head."""
    rows = _chain_rows()
    first_bad, expected, got = recompute(rows)
    head = rows[-1]["entry_hash"] if rows else GENESIS.hex()
    signature = sign_head(head)
    valid = signature_valid(head, signature, public_key_hex())
    return {
        "ok": first_bad is None and valid,
        "entries": len(rows),
        "head": head,
        "signature_valid": valid,
        "first_bad_id": first_bad,
        "expected": expected,
        "got": got,
    }
