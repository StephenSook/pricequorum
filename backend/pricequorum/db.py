"""Postgres access: one connection pool, and a schema applied idempotently at startup."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SCHEMA = Path(__file__).with_name("schema.sql")

_pool: ConnectionPool[Any] | None = None
_url: str | None = None


def normalize_url(url: str) -> str:
    """Accepts postgres:// and postgresql:// URLs. A remote host without an explicit sslmode gets
    sslmode=require (Render's external Postgres needs TLS); PQ_DB_SSLMODE overrides it."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    parts = urlsplit(url)
    host = parts.hostname or ""
    query = dict(parse_qsl(parts.query))
    override = os.environ.get("PQ_DB_SSLMODE")
    if override:
        query["sslmode"] = override
    elif "sslmode" not in query and "." in host and host not in ("localhost", "127.0.0.1"):
        query["sslmode"] = "require"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def init(url: str) -> bool:
    """Opens the pool once. Returns True when this call opened it."""
    global _pool, _url
    if _pool is not None:
        return False
    _url = normalize_url(url)
    _pool = ConnectionPool(
        _url,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row, "autocommit": True},
        open=True,
    )
    _pool.wait(timeout=60)
    return True


def close() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connect() -> Iterator[psycopg.Connection[Any]]:
    if _pool is None:
        raise RuntimeError("the database pool is not initialised")
    with _pool.connection() as conn:
        yield conn


def dedicated() -> psycopg.Connection[Any]:
    """A connection outside the pool, for session-level advisory locks held across a run."""
    if _url is None:
        raise RuntimeError("the database pool is not initialised")
    return psycopg.connect(_url, autocommit=True, row_factory=dict_row)


def migrate() -> None:
    with connect() as conn:
        conn.execute(SCHEMA.read_text())


def healthy() -> bool:
    """Cheap check with a short wait, so /api/health answers quickly even when the database is down."""
    if _pool is None:
        return False
    try:
        with _pool.connection(timeout=3) as conn:
            conn.execute("select 1")
        return True
    except Exception:  # noqa: BLE001 - health must answer, not raise
        return False
