#!/usr/bin/env python3
"""Capture bounded, pseudonymized live venue payloads as replay fixtures.

Reads only public, unauthenticated endpoints:

* Hyperliquid ``POST /info`` — ``recentTrades`` (to find an active public
  wallet), then ``userFillsByTime`` and ``clearinghouseState`` for it.
* Polymarket Data API v2 ``/v2/trades`` and ``/v2/positions`` for an active
  public wallet, plus Gamma ``/markets`` for the traded conditions.

Privacy: every wallet address is replaced with a deterministic placeholder,
and display fields (name, pseudonym, bio, profile images) are dropped before
anything is written. Numeric fields and identifiers of public markets are kept
so normalization and position reconstruction run on real shapes.

Usage::

    python scripts/capture_venue_fixtures.py [--out DIR] [--limit N]

This is evidence tooling: it never writes to a venue and needs no credential.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "services" / "api" / "tests" / "fixtures" / "provider_payloads" / "derivatives"
HL = "https://api.hyperliquid.xyz/info"
PM_DATA = "https://data-api.polymarket.com/v2"
PM_GAMMA = "https://gamma-api.polymarket.com/markets"
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
_HEADERS = {"user-agent": "aether-fixture-capture/1", "accept": "application/json"}
_TX_KEYS = {"hash", "transaction_hash", "transactionHash"}
_DROP_KEYS = {
    "name", "pseudonym", "bio", "profile_image", "profile_image_optimized",
    "profileImage", "icon", "image", "verified", "users",
}


def _post(url: str, body: dict[str, Any]) -> Any:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={**_HEADERS, "content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - fixed public hosts
        return json.loads(resp.read())


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - fixed public hosts
        return json.loads(resp.read())


class Pseudonymizer:
    """Map each real wallet to a stable placeholder within one capture."""

    def __init__(self) -> None:
        self._map: dict[str, str] = {}

    def address(self, value: str) -> str:
        key = value.lower()
        if key not in self._map:
            digest = hashlib.sha256(key.encode()).hexdigest()[:8]
            self._map[key] = "0x" + f"{len(self._map) + 1:04d}".rjust(32, "0") + digest
        return self._map[key]

    def tx_hash(self, value: str) -> str:
        # Transaction hashes resolve back to wallets on-chain; replace them too.
        return "0x" + hashlib.sha256(("tx:" + value.lower()).encode()).hexdigest()

    def scrub(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (self.tx_hash(v) if k in _TX_KEYS and isinstance(v, str) else self.scrub(v))
                for k, v in value.items()
                if k not in _DROP_KEYS
            }
        if isinstance(value, list):
            return [self.scrub(v) for v in value]
        if isinstance(value, str) and _ADDRESS.fullmatch(value):
            return self.address(value)
        return value


def capture_hyperliquid(p: Pseudonymizer, limit: int) -> dict[str, Any]:
    trades = _post(HL, {"type": "recentTrades", "coin": "HYPE"})
    wallet = next(u for t in trades for u in t.get("users", []))
    fills = _post(HL, {"type": "userFillsByTime", "user": wallet, "startTime": 0})[:limit]
    clearing = _post(HL, {"type": "clearinghouseState", "user": wallet})
    return {
        "venue": "hyperliquid",
        "account_ref": p.address(wallet),
        "user_fills_by_time": p.scrub(fills),
        "clearinghouse_state": p.scrub(clearing),
    }


def capture_polymarket(p: Pseudonymizer, limit: int) -> dict[str, Any]:
    recent = _get(f"{PM_DATA}/trades?limit=1")["data"]
    wallet = recent[0]["proxy_wallet"]
    trades = _get(f"{PM_DATA}/trades?user={wallet}&limit={limit}")
    positions = _get(f"{PM_DATA}/positions?user={wallet}&limit={limit}")
    conditions = sorted({t["condition_id"] for t in trades.get("data", [])})[:5]
    markets = []
    for condition in conditions:
        markets.extend(_get(f"{PM_GAMMA}?condition_ids={condition}"))
    for page in (trades, positions):
        page.get("pagination", {}).pop("next_cursor", None)
        page.get("pagination", {})["has_more"] = False
    return {
        "venue": "polymarket",
        "account_ref": p.address(wallet),
        "trades": p.scrub(trades),
        "positions": p.scrub(positions),
        "gamma_markets": p.scrub(markets),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for name, fn in (("hyperliquid", capture_hyperliquid), ("polymarket", capture_polymarket)):
        payload = fn(Pseudonymizer(), args.limit)
        payload["capture"] = {
            "captured_at": captured_at,
            "source": "public unauthenticated endpoints",
            "transform": "wallet addresses and transaction hashes pseudonymized; display fields dropped",
            "tool": "scripts/capture_venue_fixtures.py",
        }
        path = args.out / f"{name}_live_capture.json"
        path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
