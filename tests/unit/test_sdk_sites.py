"""SDK sites — the unit a publishable key is bound to.

A publishable key ships in page HTML, where anyone can read it. The site is
what stops a key lifted off one customer's page from being replayed against
every other property the tenant owns, so the interesting properties here are
the ones that keep the binding meaningful:

  * a site id is unguessable, because it appears in page HTML;
  * an origin is one a snippet may actually be served on;
  * a site cannot be deleted out from under a key that still names it.

The snippet half of this file is about a different failure: the snippet is
written here and read by the loader, in another language, with nothing linking
them at runtime. An attribute the loader does not know is ignored silently, so
the install reports nothing and delivers nothing.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "services" / "backend"
ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

from services.sdk_distribution.sites import (  # noqa: E402
    SITE_ID_PREFIX,
    SiteOriginError,
    new_site_id,
    normalize_origin,
    normalize_origins,
)
from services.sdk_distribution.snippet import (  # noqa: E402
    ATTR_KEY,
    ATTR_SITE,
    LOADER_URL,
    build_snippet,
)


# ── Site identity ────────────────────────────────────────────────────────────

def test_site_ids_are_unguessable_not_sequential():
    """A site id travels in page HTML and in request headers. A sequential id
    would let anyone enumerate a tenant's other properties from one page."""
    ids = {new_site_id() for _ in range(500)}
    assert len(ids) == 500
    assert all(i.startswith(SITE_ID_PREFIX) for i in ids)
    # 8 random bytes — long enough that guessing is not a strategy.
    assert all(len(i) == len(SITE_ID_PREFIX) + 16 for i in ids)


# ── Origins ──────────────────────────────────────────────────────────────────

def test_bare_host_reads_as_https():
    """What an operator pastes. Guessing is only unsafe in the direction of
    less transport security, and https is the more secure reading."""
    assert normalize_origin("example.com") == "https://example.com"
    assert normalize_origin("  www.example.com  ") == "https://www.example.com"


def test_cleartext_is_refused_off_localhost():
    """The snippet carries a publishable key, so cleartext would put it on the
    wire for anyone on the path."""
    with pytest.raises(SiteOriginError):
        normalize_origin("http://example.com")
    assert normalize_origin("http://localhost:3000") == "http://localhost:3000"


def test_default_ports_are_stripped_and_real_ones_kept():
    assert normalize_origin("https://example.com:443") == "https://example.com"
    assert normalize_origin("http://localhost:80") == "http://localhost"
    assert normalize_origin("https://example.com:8443") == "https://example.com:8443"


def test_wildcards_are_refused_rather_than_stored_unenforced():
    """Nothing downstream implements "any subdomain". Accepting one would put a
    claim in the registry that is never checked, which is worse than refusing."""
    with pytest.raises(SiteOriginError):
        normalize_origin("https://*.example.com")


def test_paths_queries_and_nonsense_are_refused():
    for bad in ("", "   ", "ftp://example.com", "https://", "https://exa mple.com"):
        with pytest.raises(SiteOriginError):
            normalize_origin(bad)


def test_origins_keep_their_order_and_lose_their_duplicates():
    """Deduplicated after normalization, so `example.com` and
    `https://example.com:443` are understood to be the same origin."""
    assert normalize_origins(["example.com", "https://example.com:443", "cdn.example.com"]) == [
        "https://example.com",
        "https://cdn.example.com",
    ]


# ── The registry ─────────────────────────────────────────────────────────────

def _repo():
    from services.sdk_distribution.sites import SDKSiteRepository

    return SDKSiteRepository()


def _registered(tenant_id: str, **overrides) -> dict:
    """Register a site directly on the repository (the routes add policy)."""
    import asyncio

    record = {
        "tenant_id": tenant_id,
        "name": overrides.pop("name", "Site"),
        "origins": ["https://example.com"],
        "environment": "production",
        "status": overrides.pop("status", "active"),
    }
    record.update(overrides)
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        _repo().insert(new_site_id(), record)
    )


def _run(coro):
    import asyncio

    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_another_tenants_site_is_not_found_rather_than_forbidden():
    """A 403 would confirm that someone else's site exists. The lookup returns
    nothing, so the route's 404 says only that it is not yours."""
    record = _registered("t-sites-a")
    assert _run(_repo().get("t-sites-a", record["id"]))["id"] == record["id"]
    assert _run(_repo().get("t-sites-b", record["id"])) is None


def test_revoked_sites_are_listed_only_when_asked_for():
    """Revoked sites are kept, not deleted — events already attributed to them
    are historical fact, and forgetting the site would orphan that history."""
    tenant = "t-sites-revoked"
    live = _registered(tenant, name="Live")
    dead = _registered(tenant, name="Dead", status="revoked")

    listed = _run(_repo().list_for_tenant(tenant))
    assert [r["id"] for r in listed] == [live["id"]]

    every = _run(_repo().list_for_tenant(tenant, include_revoked=True))
    assert {r["id"] for r in every} == {live["id"], dead["id"]}


# ── The snippet ──────────────────────────────────────────────────────────────

def test_snippet_carries_the_key_the_site_and_the_loader():
    snippet = build_snippet(site_id="site_abc", api_key="pk_live_xyz")
    assert snippet.startswith("<script async src=")
    assert f'src="{LOADER_URL}"' in snippet
    assert f'{ATTR_KEY}="pk_live_xyz"' in snippet
    assert f'{ATTR_SITE}="site_abc"' in snippet


def test_snippet_escapes_what_it_interpolates():
    """Attribute values are quoted, so a value carrying a quote would close the
    attribute and inject a second one."""
    snippet = build_snippet(site_id='site_"><script>', api_key="pk_x")
    assert '"><script>' not in snippet
    assert "&quot;" in snippet


def test_snippet_omits_optional_attributes_it_was_not_given():
    bare = build_snippet(site_id="site_a", api_key="pk_x")
    assert "data-autocapture" not in bare
    assert "data-consent" not in bare

    tuned = build_snippet(
        site_id="site_a", api_key="pk_x", autocapture="off", consent_mode="required"
    )
    assert 'data-autocapture="off"' in tuned
    assert 'data-consent="required"' in tuned


def test_every_attribute_the_snippet_emits_is_one_the_loader_reads():
    """The two halves of this contract live in different languages with nothing
    linking them at runtime, so the check has to be made against the loader's
    own source. `scripts/validate_sdk_quickstart_snippet.py` is the same check
    as a repo gate; this one fails in the unit suite, next to the code."""
    loader_src = (ROOT / "packages/web/src/loader/auto-init.ts").read_text(encoding="utf-8")
    block = re.search(r"const ATTRIBUTE_MAP = \{(.*?)\} as const;", loader_src, re.DOTALL)
    assert block, "loader ATTRIBUTE_MAP not found — the contract cannot be checked"
    loader_attributes = set(re.findall(r"""['"](data-[a-z-]+)['"]\s*:""", block.group(1)))

    emitted = set(re.findall(
        r"""['"](data-[a-z-]+)['"]""",
        (BACKEND / "services/sdk_distribution/snippet.py").read_text(encoding="utf-8"),
    ))
    assert emitted, "the snippet builder emits no data-* attributes"
    assert emitted <= loader_attributes, (
        "the snippet can emit attributes the loader ignores (ignored silently, so "
        f"the install would report nothing): {sorted(emitted - loader_attributes)}"
    )
    assert {ATTR_KEY, ATTR_SITE} <= emitted, "the snippet must carry the key and the site"


def test_loader_url_is_the_one_the_shipping_bundle_advertises():
    """Snippets are pasted into customer HTML and outlive the deploy that
    rendered them, so a URL that 404s is not a typo — it is every install."""
    bundle = (ROOT / "packages/web/rollup.loader.mjs").read_text(encoding="utf-8")
    advertised = set(re.findall(r"https://cdn\.aether\.network/[A-Za-z0-9._/-]*\.js", bundle))
    assert advertised, "the loader bundle advertises no CDN URL"
    assert LOADER_URL in advertised
