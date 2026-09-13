# PriceQuorum MCP server

Four Model Context Protocol tools over Streamable HTTP. Each tool calls the public PriceQuorum backend API,
so the MCP server holds no vendor credentials and cannot write anything the API would not.

| Tool | Backend call | What it returns |
| --- | --- | --- |
| `run_price_change(request_text)` | `POST /api/runs` | `run_id` and `events_url`. Nothing is written until a person approves in Slack. |
| `get_run(run_id)` | `GET /api/runs/{run_id}` | Status, outcome, remedy, per-app read-backs, ledger rows, signed chain head. |
| `verify_chain()` | `POST /api/ledger/verify` | The server's recomputation of the hash chain and the Ed25519 head signature. |
| `get_proof()` | `GET /api/proof` | Evaluation pass rate with its interval, refusals and named failures. |

Every tool returns `{"ok": true, "status": ..., "data": ...}` or `{"ok": false, "reason": ..., "remedy": ...}`.
A backend that is down or answers an error becomes a refusal with a remedy, never a protocol error.

The server runs stateless with JSON responses, so a plain HTTP POST is enough to call it.

## Run it standalone

```sh
cd backend
uv run --with mcp --with uvicorn python -m mcp_server.server --base-url https://<backend-host> --port 8765
```

`--allowed-host <name>` (repeatable) turns on DNS rebinding protection for those host names.

## List the tools

```sh
curl -s http://127.0.0.1:8765/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## Call a tool

```sh
curl -s http://127.0.0.1:8765/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_proof","arguments":{}}}'
```

## Mount it inside the backend at /mcp

A mounted app's lifespan does not run on its own, so the parent app starts the session manager:

```python
from mcp_server.server import build_mcp_app

mcp_app = build_mcp_app(base_url)


@asynccontextmanager
async def lifespan(app):
    async with mcp_app.state.mcp_server.session_manager.run():
        yield


app.mount("/mcp", mcp_app)
```

The endpoint is then `https://<backend-host>/mcp/` (with the trailing slash).

## Tests

```sh
cd backend
uv run --with mcp pytest -q tests/evals/test_mcp_server.py
```

Built on the `mcp` Python SDK 2.x (`mcp.server.mcpserver.MCPServer`).
