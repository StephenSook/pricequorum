FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY pricequorum ./pricequorum
COPY mcp_server ./mcp_server
RUN uv sync --frozen --no-dev

# mcp_server is a top-level package beside pricequorum; the API mounts it at /mcp/.
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn pricequorum.api.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
