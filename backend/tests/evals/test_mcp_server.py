import contextlib
import importlib.util
import json
import os

import httpx
import pytest

# A skipped MCP suite in CI would be a green check over tests that never ran, so CI fails instead.
if importlib.util.find_spec("mcp") is None:
    if os.environ.get("CI"):
        raise RuntimeError("the mcp SDK is not installed: add mcp>=2.2 to backend/pyproject.toml dependencies")
    pytest.skip("the mcp SDK is not installed; run with uv run --with mcp", allow_module_level=True)

from fastapi import FastAPI  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from mcp_server.server import build_mcp_app  # noqa: E402

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


def backend(handler):
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def tool_payload(response: httpx.Response) -> dict:
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    if result.get("structuredContent"):
        return result["structuredContent"]
    return json.loads(result["content"][0]["text"])


def test_tools_list_over_plain_http_post():
    app = build_mcp_app("https://backend.test", client_factory=backend(lambda request: httpx.Response(500)))
    with TestClient(app) as client:
        response = client.post("/", json=rpc("tools/list"), headers=HEADERS)
    assert response.status_code == 200, response.text
    names = sorted(tool["name"] for tool in response.json()["result"]["tools"])
    assert names == ["get_proof", "get_run", "run_price_change", "verify_chain"]


def test_get_proof_returns_the_backend_body():
    proof = {"scenarios": {"passed": 13, "total": 20}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/proof"
        return httpx.Response(200, json=proof)

    app = build_mcp_app("https://backend.test", client_factory=backend(handler))
    with TestClient(app) as client:
        response = client.post("/", json=rpc("tools/call", {"name": "get_proof", "arguments": {}}), headers=HEADERS)
    payload = tool_payload(response)
    assert payload["ok"] is True and payload["data"] == proof


def test_a_backend_failure_is_a_refusal_not_an_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "database down", "remedy": "wait for the database"})

    app = build_mcp_app("https://backend.test", client_factory=backend(handler))
    with TestClient(app) as client:
        response = client.post("/", json=rpc("tools/call", {"name": "verify_chain", "arguments": {}}), headers=HEADERS)
    payload = tool_payload(response)
    assert payload == {"ok": False, "reason": "database down", "remedy": "wait for the database"}


def test_get_run_refuses_a_malformed_run_id_without_calling_the_backend():
    calls = []
    app = build_mcp_app(
        "https://backend.test", client_factory=backend(lambda request: calls.append(request) or httpx.Response(200))
    )
    with TestClient(app) as client:
        response = client.post(
            "/", json=rpc("tools/call", {"name": "get_run", "arguments": {"run_id": "../../etc"}}), headers=HEADERS
        )
    payload = tool_payload(response)
    assert payload["ok"] is False and not calls


def test_mounts_into_a_fastapi_app_at_mcp():
    mcp_app = build_mcp_app("https://backend.test", client_factory=backend(lambda request: httpx.Response(500)))

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with mcp_app.state.mcp_server.session_manager.run():
            yield

    parent = FastAPI(lifespan=lifespan)
    parent.mount("/mcp", mcp_app)
    with TestClient(parent) as client:
        response = client.post("/mcp/", json=rpc("tools/list"), headers=HEADERS)
    assert response.status_code == 200, response.text
    assert len(response.json()["result"]["tools"]) == 4
