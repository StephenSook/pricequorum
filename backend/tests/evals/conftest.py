"""Makes the backend root importable so the tests can import evals and mcp_server.

The evaluation and MCP tests touch no database: they grade observations and call fake HTTP transports.
The shared tests/conftest.py makes a live Postgres autouse for every test, so these same-named fixtures
replace it here and the suite runs whether or not the local test database is up.
"""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    yield


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    yield
