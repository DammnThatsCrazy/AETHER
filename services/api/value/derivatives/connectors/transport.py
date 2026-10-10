"""Injectable REST backfill engine for derivatives venue connectors.

Root-cause design: every venue connector needs the *same* resilient request
machinery — authenticated request construction, bounded cursor pagination,
rate-limit / retry / timeout handling, and error classification — differing only
in endpoints and payload shapes. That machinery lives here ONCE and is shared by
Hyperliquid / dYdX / GMX / Drift.

Import-safe + offline by default: ``httpx`` is imported only inside methods and
only when a request is actually issued. The HTTP transport is INJECTABLE
(``http_transport``) so tests drive every path against an in-process
``httpx.MockTransport`` with NO live network. Left ``None`` in production, real
IO is performed.

Observation-only: this engine only ever issues the GET/read requests a venue
connector constructs. It never carries mutating verbs on behalf of the caller;
the connector's ``build_request`` is responsible for read-only endpoints.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional

# ── Provider-health classification tokens ─────────────────────────────────────
# ``ok`` is the only healthy pull state; the rest are degraded / off-ramp
# classifications the connector records on provider health and the fleet reports.
PROVIDER_HEALTH_OK = "ok"
PROVIDER_HEALTH_NOT_CONFIGURED = "not_configured"
PROVIDER_HEALTH_RATE_LIMITED = "rate_limited"
PROVIDER_HEALTH_AUTH_ERROR = "auth_error"
PROVIDER_HEALTH_CLIENT_ERROR = "client_error"
PROVIDER_HEALTH_SERVER_ERROR = "server_error"
PROVIDER_HEALTH_TIMEOUT = "timeout"
PROVIDER_HEALTH_NETWORK_ERROR = "network_error"
PROVIDER_HEALTH_BAD_RESPONSE = "bad_response"

HEALTHY_PROVIDER_STATES = frozenset({PROVIDER_HEALTH_OK})


class ProviderRequestError(Exception):
    """A classified failure of a venue read request.

    ``classification`` is one of the ``PROVIDER_HEALTH_*`` tokens so the caller
    can persist provider health and decide whether to degrade rather than crash.
    Never carries response bodies or secrets — only a short, safe detail string.
    """

    def __init__(
        self,
        classification: str,
        detail: str = "",
        status_code: Optional[int] = None,
    ) -> None:
        self.classification = classification
        self.status_code = status_code
        super().__init__(detail or classification)


class RestBackfillClient:
    """Resilient, injectable REST client used by venue connectors for backfill.

    Parameters
    ----------
    http_transport:
        An ``httpx`` transport (e.g. ``httpx.MockTransport``) threaded into every
        client this object opens. Tests set it to route all requests to an
        in-process handler; production leaves it ``None`` for real IO.
    base_url:
        Optional default base URL prepended to relative request paths.
    http_timeout / max_retries / backoff_base:
        Bounded resilience knobs. ``sleeper`` lets tests skip real backoff waits.
    """

    def __init__(
        self,
        *,
        http_transport: Any = None,
        base_url: str = "",
        http_timeout: float = 15.0,
        sleeper: Optional[Callable[[float], Awaitable[Any]]] = None,
        max_retries: int = 3,
        backoff_base: float = 0.2,
    ) -> None:
        self._http_transport = http_transport
        self.base_url = base_url.rstrip("/")
        self._http_timeout = http_timeout
        self._sleeper: Callable[[float], Awaitable[Any]] = sleeper or asyncio.sleep
        self._max_retries = max(0, int(max_retries))
        self._backoff_base = float(backoff_base)

    # ── client lifecycle ──────────────────────────────────────────────────
    def _open_client(self, *, timeout: Optional[float] = None):
        """Open an ``httpx.AsyncClient`` bound to the injected transport (if any).

        Imported inside the method so module import never pulls in ``httpx`` and
        never touches the network. With ``_http_transport`` set (tests), all
        requests route to that mock transport — no live IO.
        """
        import httpx

        kwargs: dict[str, Any] = {
            "timeout": timeout if timeout is not None else self._http_timeout,
        }
        if self._http_transport is not None:
            kwargs["transport"] = self._http_transport
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return httpx.AsyncClient(**kwargs)

    @staticmethod
    def _mark_health(health: Optional[dict], value: str) -> None:
        if isinstance(health, dict):
            health["health"] = value

    def _retry_delay(self, attempt: int, response: Any) -> float:
        """Backoff seconds for a retry: honor ``Retry-After`` else exponential."""
        if response is not None:
            retry_after = response.headers.get("Retry-After") or response.headers.get(
                "retry-after"
            )
            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except (TypeError, ValueError):
                    pass
        return self._backoff_base * (2 ** attempt)

    # ── single request ────────────────────────────────────────────────────
    async def request_json(
        self,
        request: dict[str, Any],
        *,
        client: Any = None,
        health: Optional[dict] = None,
    ) -> Any:
        """Execute one read request with retries / backoff / timeout and classify.

        ``request`` is a mapping with ``url`` (required) and optional
        ``method`` (default GET), ``headers``, ``params``, ``timeout``. Returns
        parsed JSON, or raises ``ProviderRequestError`` with a
        ``PROVIDER_HEALTH_*`` classification. Never logs secrets or bodies.

        A caller-owned ``client`` may be passed to reuse a connection across
        pages; otherwise a client is opened and closed for this request.
        """
        if client is not None:
            return await self._request_json_with(client, request, health=health)
        async with self._open_client(timeout=request.get("timeout")) as owned:
            return await self._request_json_with(owned, request, health=health)

    async def _request_json_with(
        self, client: Any, request: dict[str, Any], *, health: Optional[dict]
    ) -> Any:
        import httpx

        method = str(request.get("method", "GET")).upper()
        url = request["url"]
        headers = request.get("headers") or {}
        params = request.get("params") or {}
        json_body = request.get("json")
        timeout = request.get("timeout", self._http_timeout)

        attempt = 0
        classification = PROVIDER_HEALTH_NETWORK_ERROR
        while True:
            response = None
            try:
                kwargs: dict[str, Any] = {
                    "headers": headers,
                    "params": params,
                    "timeout": timeout,
                }
                if json_body is not None:
                    kwargs["json"] = json_body
                response = await client.request(method, url, **kwargs)
            except httpx.TimeoutException:
                classification = PROVIDER_HEALTH_TIMEOUT
            except httpx.HTTPError:
                classification = PROVIDER_HEALTH_NETWORK_ERROR
            else:
                status = response.status_code
                if status == 429 or status >= 500:
                    classification = (
                        PROVIDER_HEALTH_RATE_LIMITED
                        if status == 429
                        else PROVIDER_HEALTH_SERVER_ERROR
                    )
                    if attempt < self._max_retries:
                        await self._sleeper(self._retry_delay(attempt, response))
                        attempt += 1
                        continue
                    self._mark_health(health, classification)
                    raise ProviderRequestError(classification, f"HTTP {status}", status)
                if status in (401, 403):
                    self._mark_health(health, PROVIDER_HEALTH_AUTH_ERROR)
                    raise ProviderRequestError(
                        PROVIDER_HEALTH_AUTH_ERROR, f"HTTP {status}", status
                    )
                if status >= 400:
                    self._mark_health(health, PROVIDER_HEALTH_CLIENT_ERROR)
                    raise ProviderRequestError(
                        PROVIDER_HEALTH_CLIENT_ERROR, f"HTTP {status}", status
                    )
                try:
                    # Parse provider numbers as Decimal, never binary float, so
                    # the derivatives decimal-only invariant holds end to end
                    # even when a venue serializes amounts as bare JSON numbers.
                    return json.loads(response.text, parse_float=Decimal)
                except (ValueError, json.JSONDecodeError) as exc:
                    self._mark_health(health, PROVIDER_HEALTH_BAD_RESPONSE)
                    raise ProviderRequestError(
                        PROVIDER_HEALTH_BAD_RESPONSE, f"invalid JSON: {exc}", status
                    )
            # timeout / network-error retry path
            if attempt < self._max_retries:
                await self._sleeper(self._retry_delay(attempt, None))
                attempt += 1
                continue
            self._mark_health(health, classification)
            raise ProviderRequestError(classification, "request failed after retries")

    # ── bounded cursor pagination ─────────────────────────────────────────
    async def paginate(
        self,
        build_request: Callable[[Optional[str]], Optional[dict[str, Any]]],
        extract_page: Callable[[Any], tuple[list[dict], Optional[str]]],
        *,
        start_cursor: Optional[str] = None,
        max_pages: int = 50,
        health: Optional[dict] = None,
    ) -> tuple[list[dict], Optional[str]]:
        """Drive bounded cursor pagination.

        ``build_request(cursor)`` returns the read-request dict for a page (or
        ``None`` to stop). ``extract_page(json)`` returns ``(records,
        next_cursor)``. Stops when ``next_cursor`` is ``None`` / unchanged, when
        a page is empty, or after ``max_pages`` pages. Returns
        ``(all_records, resume_cursor)`` where ``resume_cursor`` is where the
        next sweep should continue from.
        """
        records: list[dict] = []
        cursor = start_cursor
        pages = 0
        async with self._open_client() as client:
            while pages < max_pages:
                request = build_request(cursor)
                if request is None:
                    break
                payload = await self.request_json(request, client=client, health=health)
                page_records, next_cursor = extract_page(payload)
                records.extend(page_records)
                pages += 1
                if not page_records or next_cursor is None or next_cursor == cursor:
                    cursor = next_cursor if next_cursor is not None else cursor
                    break
                cursor = next_cursor
        if isinstance(health, dict) and not health.get("health"):
            health["health"] = PROVIDER_HEALTH_OK
        return records, cursor


__all__ = [
    "PROVIDER_HEALTH_OK",
    "PROVIDER_HEALTH_NOT_CONFIGURED",
    "PROVIDER_HEALTH_RATE_LIMITED",
    "PROVIDER_HEALTH_AUTH_ERROR",
    "PROVIDER_HEALTH_CLIENT_ERROR",
    "PROVIDER_HEALTH_SERVER_ERROR",
    "PROVIDER_HEALTH_TIMEOUT",
    "PROVIDER_HEALTH_NETWORK_ERROR",
    "PROVIDER_HEALTH_BAD_RESPONSE",
    "HEALTHY_PROVIDER_STATES",
    "ProviderRequestError",
    "RestBackfillClient",
]
