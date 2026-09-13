"""Shared HTTP handling for the Notion and Airtable adapters.

Maps transport failures to AdapterFault and business errors to AdapterRefusal, and retries a
429 (the only status that guarantees the request was not processed) with a bounded backoff.

Only a 2xx response carrying a JSON object counts as success. A redirect, or a success status
with an HTML page or any other non-object body, is a fault: the caller cannot tell what the app
did, so it must never be read as an unlocked record or a completed write.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

import httpx

from pricequorum.ports import AdapterFault, AdapterRefusal, AppName

Sleep = Callable[[float], None]
RemedyFor = Callable[[int, dict[str, Any]], str]


def request_json(
    client: httpx.Client,
    *,
    app: AppName,
    call_site: str,
    method: str,
    url: str,
    headers: dict[str, str],
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    sleep: Sleep,
    max_retries: int,
    retry_delay: Callable[[int, httpx.Response], float],
    remedy_for: RemedyFor,
) -> dict[str, Any]:
    for attempt in range(max_retries + 1):
        try:
            response = client.request(method, url, headers=headers, json=json, params=params)
        except httpx.TimeoutException as error:
            raise AdapterFault("timeout", call_site, False, str(error)[:200]) from error
        except httpx.TransportError as error:
            raise AdapterFault("timeout", call_site, False, f"transport error: {error}"[:200]) from error

        status = response.status_code
        if status == 429:
            if attempt >= max_retries:
                raise AdapterFault("rate_limit", call_site, False, f"still rate limited after {attempt + 1} attempts")
            sleep(retry_delay(attempt, response))
            continue
        if status >= 500:
            raise AdapterFault("server_5xx", call_site, False, f"HTTP {status}")
        if status == 409:
            body = _error_body(response)
            raise AdapterFault("conflict_409", call_site, False, str(body.get("message", "conflict"))[:200])
        if status >= 400:
            body = _error_body(response)
            detail = body.get("message") or body.get("error") or f"HTTP {status}"
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("type") or f"HTTP {status}"
            raise AdapterRefusal(app, f"{app} refused {call_site}: {detail}", remedy_for(status, body))
        if not 200 <= status < 300:
            raise AdapterFault("server_5xx", call_site, False, f"unexpected HTTP {status}; redirects are not followed")
        return _success_body(response, call_site)
    raise AdapterFault("rate_limit", call_site, False, "retries exhausted")  # pragma: no cover


def _success_body(response: httpx.Response, call_site: str) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as error:
        raise AdapterFault(
            "server_5xx", call_site, False, f"HTTP {response.status_code} with a body that is not JSON"
        ) from error
    if not isinstance(data, dict):
        raise AdapterFault(
            "server_5xx", call_site, False, f"HTTP {response.status_code} with a body that is not an object"
        )
    return data


def _error_body(response: httpx.Response) -> dict[str, Any]:
    """Error bodies are read leniently: they only shape the refusal message."""
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {"data": data}


def retry_after_or_backoff(attempt: int, response: httpx.Response) -> float:
    header = response.headers.get("Retry-After")
    try:
        return max(0.0, float(header)) if header is not None else float(2**attempt)
    except ValueError:
        return float(2**attempt)


def airtable_penalty(attempt: int, response: httpx.Response, jitter: Callable[[], float] = random.random) -> float:
    """Airtable asks clients to wait 30 seconds after a 429."""
    return 30.0 + 3.0 * jitter()
