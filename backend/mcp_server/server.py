"""PriceQuorum MCP server over Streamable HTTP.

Four tools call the public PriceQuorum backend API: start a price change (still gated by a person in
Slack before anything is written), read a run, verify the ledger chain, and read the evaluation proof.
Every tool returns a structured result and refuses with a reason and a remedy instead of raising.

Mount it into the backend app at /mcp:

    mcp_app = build_mcp_app(base_url)
    app.mount("/mcp", mcp_app)
    # and in the FastAPI lifespan: async with mcp_app.state.mcp_server.session_manager.run(): ...

or run it standalone: python -m mcp_server.server --base-url https://<backend> --port 8765
"""

from __future__ import annotations

import argparse
import os
import re
from collections.abc import Callable
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

RUN_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
ClientFactory = Callable[[], httpx.AsyncClient]


def refusal(reason: str, remedy: str) -> dict[str, Any]:
    return {"ok": False, "reason": reason, "remedy": remedy}


async def call_backend(factory: ClientFactory, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    """One backend request. Transport errors and non-2xx answers become refusals, never exceptions."""
    try:
        async with factory() as client:
            response = await client.request(method, url, **kwargs)
    except httpx.HTTPError as error:
        return refusal(
            f"The PriceQuorum backend could not be reached ({type(error).__name__}).",
            "Check that the backend is running and answers /api/health, then try again.",
        )
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code >= 400 or not isinstance(body, dict):
        detail = body.get("detail") if isinstance(body, dict) else None
        remedy = body.get("remedy") if isinstance(body, dict) else None
        return refusal(
            str(detail) if detail else f"The backend answered with status {response.status_code}.",
            str(remedy) if remedy else "Try again once /api/health reports the backend healthy.",
        )
    return {"ok": True, "status": response.status_code, "data": body}


def build_mcp(base_url: str, client_factory: ClientFactory | None = None) -> MCPServer:
    base = base_url.rstrip("/")
    factory: ClientFactory = client_factory or (lambda: httpx.AsyncClient(timeout=30.0))
    server: MCPServer = MCPServer(
        name="pricequorum",
        instructions=(
            "PriceQuorum changes a SaaS plan price once across Stripe, Notion and Airtable. Starting a change "
            "never writes by itself: a person approves it in Slack first, and the run reads every app back."
        ),
    )

    @server.tool(
        description=(
            "Start a price change from plain words, for example 'raise Pro to $25/month'. Returns the run id. "
            "Nothing is written until a person approves the change in Slack."
        )
    )
    async def run_price_change(request_text: str) -> dict[str, Any]:
        text = request_text.strip()
        if not 1 <= len(text) <= 500:
            return refusal(
                "request_text must be between 1 and 500 characters.",
                "Describe the change in one sentence, for example: raise Pro to $25/month.",
            )
        return await call_backend(factory, "POST", f"{base}/api/runs", json={"request_text": text})

    @server.tool(
        description="Read one run: status, outcome, remedy, per-app read-backs, ledger rows and the signed chain head."
    )
    async def get_run(run_id: str) -> dict[str, Any]:
        if not RUN_ID.fullmatch(run_id):
            return refusal(
                "run_id must be 8 to 64 letters, digits or hyphens.", "Use the run_id returned by run_price_change."
            )
        return await call_backend(factory, "GET", f"{base}/api/runs/{run_id}")

    @server.tool(
        description="Recompute the ledger hash chain on the server and check the Ed25519 signature on its head."
    )
    async def verify_chain() -> dict[str, Any]:
        return await call_backend(factory, "POST", f"{base}/api/ledger/verify")

    @server.tool(
        description="Read the evaluation proof recomputed from the database: pass rate with interval, refusals, named failures."
    )
    async def get_proof() -> dict[str, Any]:
        return await call_backend(factory, "GET", f"{base}/api/proof")

    return server


def build_mcp_app(
    base_url: str,
    allowed_hosts: list[str] | None = None,
    client_factory: ClientFactory | None = None,
) -> Starlette:
    """A stateless Streamable HTTP ASGI app serving MCP at its root. The server is on app.state.mcp_server.

    DNS rebinding protection guards servers bound to localhost. A public deployment can pass its own host
    names in allowed_hosts to enable it; without them it is off, because the tools only call the public API.
    """
    server = build_mcp(base_url, client_factory)
    security = (
        TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts)
        if allowed_hosts
        else TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    app = server.streamable_http_app(
        streamable_http_path="/", json_response=True, stateless_http=True, transport_security=security
    )
    app.state.mcp_server = server
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="PriceQuorum MCP server (Streamable HTTP)")
    parser.add_argument("--base-url", default=os.environ.get("PQ_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allowed-host", action="append", dest="allowed_hosts")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(build_mcp_app(args.base_url, args.allowed_hosts), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
