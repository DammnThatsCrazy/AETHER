#!/usr/bin/env python3
"""Refresh the published IP ranges of AI agent / crawler providers.

Writes ``services/api/journeys/traffic/agent_provider_ranges.json``, which the
traffic classifier uses to promote a declared AI user-agent to
``platform_verified`` only when the server-observed client IP is inside the
provider's own published range. See
docs/architecture/AGENT-DETECTION-RELIABILITY.md.

Only providers that publish a machine-readable range list are listed here. Do
not add a provider by guessing an endpoint: an agent without published ranges
stays ``declared``.

Run manually (network required); review the diff before committing:

    python scripts/refresh_agent_provider_ranges.py
"""

from __future__ import annotations

import ipaddress
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "services/api/journeys/traffic/agent_provider_ranges.json"

# user-agent signature (lower-case, as in classifier.py) -> (provider, product, published list)
SOURCES: dict[str, tuple[str, str, str]] = {
    "gptbot": ("openai", "gptbot", "https://openai.com/gptbot.json"),
    "chatgpt-user": ("openai", "chatgpt", "https://openai.com/chatgpt-user.json"),
    "oai-searchbot": ("openai", "search", "https://openai.com/searchbot.json"),
    "perplexitybot": ("perplexity", "perplexity", "https://www.perplexity.ai/perplexitybot.json"),
    "perplexity-user": ("perplexity", "perplexity", "https://www.perplexity.ai/perplexity-user.json"),
}


def _fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "aether-range-refresh/1"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https URLs
        return json.load(resp)


def _prefixes(document: dict) -> list[str]:
    out: set[str] = set()
    for entry in document.get("prefixes") or []:
        raw = entry.get("ipv4Prefix") or entry.get("ipv6Prefix")
        if not raw:
            continue
        out.add(str(ipaddress.ip_network(raw, strict=False)))  # rejects anything malformed
    return sorted(out, key=lambda p: (ipaddress.ip_network(p).version, ipaddress.ip_network(p)))


def main() -> int:
    data: dict[str, dict] = {}
    for signature, (provider, product, url) in sorted(SOURCES.items()):
        document = _fetch(url)
        prefixes = _prefixes(document)
        if not prefixes:
            print(f"error: {url} returned no prefixes", file=sys.stderr)
            return 1
        data[signature] = {
            "provider": provider,
            "product": product,
            "source_url": url,
            "source_creation_time": document.get("creationTime"),
            "prefixes": prefixes,
        }
        print(f"{signature}: {len(prefixes)} prefixes")
    payload = {"schema_version": 1, "signatures": data}
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
