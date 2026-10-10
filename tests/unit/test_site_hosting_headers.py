"""The unified site keeps the hosting headers of the app it replaces.

Amplify reads customHttp.yml from the monorepo app root, so switching the
Aether host from apps/marketing-aether to apps/public-site would silently drop
its security headers and immutable asset caching without this file.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _headers(app_root: str) -> dict[str, dict[str, str]]:
    config = yaml.safe_load((ROOT / app_root / "customHttp.yml").read_text(encoding="utf-8"))
    return {
        rule["pattern"]: {header["key"]: header["value"] for header in rule["headers"]}
        for rule in config["customHeaders"]
    }


def test_site_serves_the_marketing_security_headers_and_asset_caching() -> None:
    site = _headers("apps/public-site")
    assert site == _headers("apps/marketing-aether")
    assert site["**/*"] == {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    }
    assert site["/assets/**"] == {"Cache-Control": "public, max-age=31536000, immutable"}
