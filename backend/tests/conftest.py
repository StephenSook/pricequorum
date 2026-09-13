"""Shared fixtures: a real Postgres (DATABASE_URL, default the local test database on port 55432),
a clean schema per session and clean tables per test.

The database is opened lazily, by the first test that needs it. Tests under tests/adapters exercise the
vendor adapters against fake HTTP transports and run without a database. tests/evals overrides both
fixtures by name in its own conftest.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://postgres@localhost:55432/pricequorum_test")

from pricequorum import db, ledger  # noqa: E402
from pricequorum.config import Settings  # noqa: E402

TESTS = Path(__file__).resolve().parent
NO_DATABASE = frozenset({"adapters"})

TABLES = (
    "eval_results",
    "eval_scenarios",
    "entity_resolution",
    "approvals",
    "ledger_chain",
    "action_ledger",
    "run_events",
    "runs",
)

TEST_SIGNING_SEED = "11" * 32


def _needs_database(request: pytest.FixtureRequest) -> bool:
    try:
        parts = Path(str(request.node.path)).resolve().relative_to(TESTS).parts
    except ValueError:
        return True
    return not (len(parts) > 1 and parts[0] in NO_DATABASE)


@pytest.fixture(scope="session")
def database() -> Iterator[None]:
    db.init(os.environ["DATABASE_URL"])
    with db.connect() as conn:
        conn.execute("drop schema if exists public cascade; create schema public;")
    db.migrate()
    ledger.load_signing_key(TEST_SIGNING_SEED)
    yield
    db.close()


@pytest.fixture(autouse=True)
def clean_tables(request: pytest.FixtureRequest) -> Iterator[None]:
    if not _needs_database(request):
        yield
        return
    request.getfixturevalue("database")
    with db.connect() as conn:
        conn.execute("truncate " + ", ".join(TABLES) + " restart identity cascade")
    ledger.load_signing_key(TEST_SIGNING_SEED)
    yield


@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=os.environ["DATABASE_URL"],
        stripe_secret_key="sk_test_placeholder_for_tests",
        pq_operator_token="operator-test-token",
        pq_allowed_origins="https://pricequorum-web.vercel.app,http://localhost:3000",
        pq_approval_poll_seconds=0.02,
        pq_rate_limit_wait_seconds=0,
    )
