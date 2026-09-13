"""Shared HTTP handling for the Notion and Airtable adapters.

Maps transport failures to AdapterFault and business errors to AdapterRefusal, and retries a
429 (the only status that guarantees the request was not processed) with a bounded backoff.
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

        if response.status_code == 429:
            if attempt >= max_retries:
                raise AdapterFault("rate_limit", call_site, False, f"still rate limited after {attempt + 1} attempts")
            sleep(retry_delay(attempt, response))
            continue
        body = _body(response)
        if response.status_code >= 500:
            raise AdapterFault("server_5xx", call_site, False, f"HTTP {response.status_code}")
        if response.status_code == 409:
            raise AdapterFault("conflict_409", call_site, False, str(body.get("message", "conflict"))[:200])
        if response.status_code >= 400:
            detail = body.get("message") or body.get("error") or f"HTTP {response.status_code}"
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("type") or f"HTTP {response.status_code}"
            raise AdapterRefusal(app, f"{app} refused {call_site}: {detail}", remedy_for(response.status_code, body))
        return body
    raise AdapterFault("rate_limit", call_site, False, "retries exhausted")  # pragma: no cover


def _body(response: httpx.Response) -> dict[str, Any]:
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
