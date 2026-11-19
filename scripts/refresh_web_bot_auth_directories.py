#!/usr/bin/env python3
"""Refresh the Web Bot Auth key directories of known signing agents.

Writes ``services/api/journeys/traffic/web_bot_auth_directories.json``: a
snapshot of each known signer's public Ed25519 keys, fetched from
``<signature-agent>/.well-known/http-message-signatures-directory``
(draft-meunier-web-bot-auth-architecture). Ingestion verifies HTTP Message
Signatures (RFC 9421) against this snapshot and never fetches keys itself.

Only signers that publish a directory are listed. A signer missing from the
snapshot is reported as ``web_bot_auth_unknown_signer`` (declared, unverified);
never add one by guessing a URL.

Each key is checked before it is written: OKP / Ed25519, a 32-byte public key,
and a ``kid`` equal to its RFC 7638 JWK thumbprint (when the directory gives one).

Run manually (network required); review the diff before committing:

    python scripts/refresh_web_bot_auth_directories.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "services/api/journeys/traffic/web_bot_auth_directories.json"
WELL_KNOWN = "/.well-known/http-message-signatures-directory"

# signature-agent origin -> (provider, product, actor_type)
SOURCES: dict[str, tuple[str, str, str]] = {
    "https://chatgpt.com": ("openai", "chatgpt", "agent"),
}


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def jwk_thumbprint(x: str) -> str:
    """RFC 7638 SHA-256 thumbprint of an OKP/Ed25519 JWK, base64url without padding."""
    canonical = json.dumps({"crv": "Ed25519", "kty": "OKP", "x": x}, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b"=").decode()


def _fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "aether-key-refresh/1"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https URLs
        return json.load(resp)


def _keys(document: dict) -> list[dict]:
    keys = []
    for jwk in document.get("keys") or []:
        if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519" or not jwk.get("x"):
            continue
        if len(_b64url_decode(jwk["x"])) != 32:
            continue
        thumbprint = jwk_thumbprint(jwk["x"])
        if jwk.get("kid") and jwk["kid"] != thumbprint:
            print(f"warning: skipping key whose kid is not its thumbprint: {jwk['kid']}", file=sys.stderr)
            continue
        keys.append({"kid": thumbprint, "x": jwk["x"], "nbf": jwk.get("nbf"), "exp": jwk.get("exp")})
    return sorted(keys, key=lambda k: k["kid"])


def main() -> int:
    signers: dict[str, dict] = {}
    for origin, (provider, product, actor_type) in sorted(SOURCES.items()):
        url = origin + WELL_KNOWN
        keys = _keys(_fetch(url))
        if not keys:
            print(f"error: {url} returned no usable Ed25519 keys", file=sys.stderr)
            return 1
        signers[origin] = {
            "provider": provider,
            "product": product,
            "actor_type": actor_type,
            "source_url": url,
            "keys": keys,
        }
        print(f"{origin}: {len(keys)} key(s)")
    payload = {"schema_version": 1, "signers": signers}
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
