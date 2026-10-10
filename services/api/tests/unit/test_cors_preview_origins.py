"""Per-PR preview origins: exact pr-N hosts of one suffix, never production."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient

from shared.security.cors import preview_origin_regex

SUFFIX = "d1abc23.amplifyapp.com"


def _client(regex):
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware, allow_origins=["https://app.staging.olympuslabsml.com"],
        allow_origin_regex=regex, allow_credentials=True, allow_methods=["GET"],
    )

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return TestClient(app)


def _allowed(client, origin: str) -> bool:
    response = client.get("/ping", headers={"Origin": origin})
    return response.headers.get("access-control-allow-origin") == origin


def test_only_numbered_preview_hosts_of_the_suffix_are_allowed():
    client = _client(preview_origin_regex(SUFFIX, "staging"))
    assert _allowed(client, f"https://pr-705.{SUFFIX}")
    assert _allowed(client, "https://app.staging.olympuslabsml.com")
    for origin in (
        f"http://pr-705.{SUFFIX}",                     # not https
        f"https://main.{SUFFIX}",                      # not a PR branch
        f"https://pr-705.{SUFFIX}.evil.example",       # suffix is not the host end
        f"https://pr-705x{SUFFIX}",                    # dot is literal
        f"https://evil.pr-705.{SUFFIX}",               # no extra labels
        "https://pr-705.d9other.amplifyapp.com",       # another Amplify app
        f"https://pr-705.{SUFFIX}:8443",               # no port
    ):
        assert not _allowed(client, origin), origin


def test_previews_are_off_by_default_and_refused_in_production():
    assert preview_origin_regex("", "staging") is None
    with pytest.raises(ValueError, match="production"):
        preview_origin_regex(SUFFIX, "production")


@pytest.mark.parametrize("suffix", [".*", "amplifyapp", "a..b.com", "*.amplifyapp.com", "x.com/"])
def test_a_malformed_suffix_fails_at_startup(suffix):
    with pytest.raises(ValueError):
        preview_origin_regex(suffix, "staging")
