"""Every request header the first-party browser apps send passes CORS preflight.

The Aether app sends X-Aether-Environment on every API call. It was missing
from the allow-list, so each preflight failed with 400 "Disallowed CORS
headers" and the browser reported "Failed to fetch" (staging sign-in broke on
POST /v1/auth/sso/callback).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient

from shared.security.cors import CORS_ALLOW_HEADERS

REPO = Path(__file__).resolve().parents[4]
FIRST_PARTY_APPS = ("frontend/aether/src", "frontend/kyber/src")
ORIGIN = "https://app.staging.olympuslabsml.com"
# A literal custom header used as an object key: 'X-Foo': value
_HEADER_KEY = re.compile(r"""['"](X-[A-Za-z0-9-]+)['"]\s*:""")


def _sent_headers() -> set[str]:
    files = subprocess.run(
        ["git", "ls-files", "--", *FIRST_PARTY_APPS],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()
    sent: set[str] = set()
    for name in files:
        if not name.endswith((".ts", ".tsx")) or re.search(r"(\.test\.|/test/|__tests__)", name):
            continue
        sent.update(_HEADER_KEY.findall((REPO / name).read_text(encoding="utf-8")))
    return sent


def test_every_header_the_apps_send_is_allowed():
    sent = _sent_headers()
    assert "X-Aether-Environment" in sent, "scan found no app headers; is the pattern stale?"
    allowed = {h.lower() for h in CORS_ALLOW_HEADERS}
    assert not {h for h in sent if h.lower() not in allowed}


@pytest.mark.parametrize("header", ["x-aether-environment", "x-kyber-environment", "x-correlation-id"])
def test_preflight_accepts_app_headers(header):
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware, allow_origins=[ORIGIN], allow_credentials=True,
        allow_methods=["POST"], allow_headers=list(CORS_ALLOW_HEADERS),
    )
    response = TestClient(app).options(
        "/v1/auth/sso/callback",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": f"authorization,content-type,{header}",
        },
    )
    assert response.status_code == 200, response.text
