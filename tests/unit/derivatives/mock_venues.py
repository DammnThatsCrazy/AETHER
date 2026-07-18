"""Provider-shaped mock REST/WS servers + fixtures for venue-adapter tests.

TEST-TREE ONLY — never imported by production code. Each REST builder returns an
``httpx.MockTransport`` (injected via ``http_transport=``) plus a ``MockServer``
recorder capturing every request, so tests assert on request construction,
pagination, rate-limit/retry, and timeout handling with NO live socket. WS
builders return a scripted frame-source factory (injected via ``stream_factory=``)
that yields deterministic frames and can simulate a mid-stream disconnect for
reconnect/gap-recovery tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx

from services.derivatives.connectors.stream import StreamDisconnect


# ── REST request recorder ─────────────────────────────────────────────────────
@dataclass
class MockServer:
    requests: list[httpx.Request] = field(default_factory=list)
    _429_remaining: int = 0
    _timeout_remaining: int = 0

    @property
    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def param_values(self, name: str) -> list[Optional[str]]:
        return [r.url.params.get(name) for r in self.requests]

    def header_values(self, name: str) -> list[Optional[str]]:
        return [r.headers.get(name) for r in self.requests]

    def body_types(self) -> list[Optional[str]]:
        out: list[Optional[str]] = []
        for r in self.requests:
            try:
                out.append(json.loads(r.content).get("type"))
            except (ValueError, json.JSONDecodeError):
                out.append(None)
        return out

    def transport(self, handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
        def _wrapped(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if self._timeout_remaining > 0:
                self._timeout_remaining -= 1
                raise httpx.ReadTimeout("mock injected timeout", request=request)
            if self._429_remaining > 0:
                self._429_remaining -= 1
                return httpx.Response(
                    429, headers={"Retry-After": "0"}, json={"error": "rate_limited"},
                    request=request,
                )
            return handler(request)

        return httpx.MockTransport(_wrapped)


# ── Hyperliquid: POST /info dispatched by ``type`` ────────────────────────────
def hyperliquid_transport(
    *,
    fills: list[dict],
    clearinghouse: Optional[dict] = None,
    funding: Optional[list[dict]] = None,
    rate_limit_first: int = 0,
    timeout_first: int = 0,
) -> tuple[httpx.MockTransport, MockServer]:
    """Hyperliquid ``/info``. ``fills`` are windowed by ``startTime`` (time>=cursor)."""
    server = MockServer(_429_remaining=rate_limit_first, _timeout_remaining=timeout_first)
    funding = funding or []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        kind = body.get("type")
        if kind == "userFillsByTime":
            start = int(body.get("startTime", 0))
            window = [f for f in fills if int(f["time"]) >= start]
            return httpx.Response(200, json=window, request=request)
        if kind == "userFunding":
            start = int(body.get("startTime", 0))
            window = [f for f in funding if int(f["time"]) >= start]
            return httpx.Response(200, json=window, request=request)
        if kind == "clearinghouseState":
            return httpx.Response(200, json=clearinghouse or {}, request=request)
        if kind == "meta":
            return httpx.Response(200, json={"universe": [{"name": "BTC"}]}, request=request)
        return httpx.Response(200, json=[], request=request)

    return server.transport(handler), server


def hl_fill(tid: int, time: int, side: str = "B", px: str = "60000", sz: str = "0.25") -> dict:
    return {
        "tid": tid, "time": time, "coin": "BTC", "side": side, "px": px, "sz": sz,
        "fee": "0.01", "feeToken": "USDC", "crossed": side == "B", "oid": 100 + tid,
    }


HL_CLEARINGHOUSE = {
    "time": 5000,
    "assetPositions": [
        {"position": {"coin": "BTC", "szi": "0.5", "entryPx": "60000", "unrealizedPnl": "12.5"}},
        {"position": {"coin": "ETH", "szi": "0", "entryPx": "0", "unrealizedPnl": "0"}},
    ],
    "marginSummary": {"totalMarginUsed": "300", "marginUtilization": "0.12"},
}


# ── dYdX: GET endpoints with pageCursor + explicit ``next`` ───────────────────
def dydx_transport(
    *,
    fill_pages: dict[Optional[str], tuple[list[dict], Optional[str]]],
    orders: Optional[list[dict]] = None,
    positions: Optional[list[dict]] = None,
    rate_limit_first: int = 0,
    timeout_first: int = 0,
) -> tuple[httpx.MockTransport, MockServer]:
    """dYdX Indexer. ``fill_pages`` maps incoming pageCursor -> (fills, next)."""
    server = MockServer(_429_remaining=rate_limit_first, _timeout_remaining=timeout_first)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/fills"):
            cursor = request.url.params.get("pageCursor")
            records, nxt = fill_pages.get(cursor, ([], None))
            return httpx.Response(200, json={"fills": records, "next": nxt}, request=request)
        if path.endswith("/orders"):
            return httpx.Response(200, json={"orders": orders or [], "next": None}, request=request)
        if path.endswith("/perpetualPositions"):
            return httpx.Response(200, json={"positions": positions or [], "next": None}, request=request)
        if path.endswith("/height"):
            return httpx.Response(200, json={"height": "1"}, request=request)
        return httpx.Response(200, json={}, request=request)

    return server.transport(handler), server


def dydx_fill(fid: str, side: str = "BUY", market: str = "BTC-USD") -> dict:
    return {
        "id": fid, "side": side, "size": "0.10", "price": "61000.12", "fee": "1.20",
        "feeAsset": "USDC", "market": market, "liquidity": "MAKER",
        "createdAt": "2026-07-05T00:00:00.000Z", "type": "LIMIT", "orderId": "ord-" + fid,
    }


# ── GMX: POST subgraph GraphQL, paginated by timestamp_lt ─────────────────────
def gmx_transport(
    *, trades: list[dict], rate_limit_first: int = 0, timeout_first: int = 0,
) -> tuple[httpx.MockTransport, MockServer]:
    """GMX subgraph. Returns trades with timestamp < variables.tsLt, newest first."""
    server = MockServer(_429_remaining=rate_limit_first, _timeout_remaining=timeout_first)
    ordered = sorted(trades, key=lambda t: int(t["timestamp"]), reverse=True)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        variables = body.get("variables", {})
        if "_meta" in body.get("query", ""):
            return httpx.Response(200, json={"data": {"_meta": {"block": {"number": 1}}}}, request=request)
        ts_lt = int(variables.get("tsLt", 2_000_000_000))
        first = int(variables.get("first", 100))
        window = [t for t in ordered if int(t["timestamp"]) < ts_lt][:first]
        return httpx.Response(200, json={"data": {"trades": window}}, request=request)

    return server.transport(handler), server


def gmx_trade(tid: str, timestamp: int, is_long: bool = True) -> dict:
    return {
        "id": tid, "account": "0xabc", "indexToken": "ETH", "isLong": is_long,
        "sizeDelta": "100.00", "price": "3400.01", "collateralDelta": "50.00",
        "feeUsd": "0.40", "timestamp": timestamp,
    }


# ── Drift: GET /trades with page cursor + explicit ``next`` ───────────────────
def drift_transport(
    *,
    trade_pages: dict[Optional[str], tuple[list[dict], Optional[str]]],
    funding: Optional[list[dict]] = None,
    rate_limit_first: int = 0,
    timeout_first: int = 0,
) -> tuple[httpx.MockTransport, MockServer]:
    server = MockServer(_429_remaining=rate_limit_first, _timeout_remaining=timeout_first)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/trades"):
            cursor = request.url.params.get("page")
            records, nxt = trade_pages.get(cursor, ([], None))
            return httpx.Response(200, json={"records": records, "next": nxt}, request=request)
        if path.endswith("/fundingPayments"):
            return httpx.Response(200, json={"records": funding or [], "next": None}, request=request)
        if path.endswith("/status"):
            return httpx.Response(200, json={"status": "ok"}, request=request)
        return httpx.Response(200, json={"records": [], "next": None}, request=request)

    return server.transport(handler), server


def drift_trade(fid: str, ts: int, direction: str = "long") -> dict:
    return {
        "fillId": fid, "marketName": "SOL-PERP", "direction": direction,
        "price": "150.00", "baseAssetAmount": "2.5", "fee": "0.05", "feeAsset": "USDC",
        "liquidity": "taker", "ts": ts, "takerOrderId": "ord-" + fid,
    }


# ── WebSocket scripted frame-source factory ───────────────────────────────────
@dataclass
class WSCalls:
    n: int = 0
    resumes: list[Optional[int]] = field(default_factory=list)


def scripted_ws_factory(
    connections: list[tuple[str, list[dict]]],
) -> tuple[Callable[[Optional[int]], Any], WSCalls]:
    """Build a frame-source factory replaying scripted connections.

    Each connection is ``("frames", [...])`` to end cleanly, or
    ``("disconnect", [...])`` to yield the frames then raise ``StreamDisconnect``
    (a recoverable drop). The factory records the resume cursor it was opened
    with on each (re)connect.
    """
    calls = WSCalls()

    def factory(resume: Optional[int]):
        idx = calls.n
        calls.n += 1
        calls.resumes.append(resume)
        kind, frames = connections[idx] if idx < len(connections) else ("frames", [])

        async def gen():
            for frame in frames:
                yield frame
            if kind == "disconnect":
                raise StreamDisconnect("scripted drop")

        return gen()

    return factory, calls


def ws_frame(sequence: int, tid: int) -> dict:
    return {"sequence": sequence, "payload": {"channel": "userFills", "fills": [hl_fill(tid, 1000 + tid)]}}
