"""Trusted-proxy resolution, geo providers, and IP HMAC — no raw IP escapes."""
from __future__ import annotations

import re

import pytest

from shared.temporal.instant import parse_instant_strict

AT = parse_instant_strict("2026-07-15T12:00:00Z")
_IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


def _config(monkeypatch, *, cidrs=(), cloudflare=False):
    import config.settings as settings_module
    from config.settings import ContextIntelligenceConfig

    monkeypatch.setattr(
        settings_module.settings,
        "context_intelligence",
        ContextIntelligenceConfig(
            enrichment_enabled=True,
            trusted_proxy_cidrs=list(cidrs),
            cloudflare_proxy_enabled=cloudflare,
        ),
    )
    # trusted-network cache keys off settings — reset between tests
    from services.ingestion import context_enricher

    context_enricher._trusted_networks.cache_clear()


class TestResolveClientIp:
    def test_untrusted_peer_headers_ignored(self, monkeypatch):
        _config(monkeypatch, cidrs=())
        from services.ingestion.context_enricher import resolve_client_ip

        ip, source = resolve_client_ip("203.0.113.7", "8.8.8.8, 1.1.1.1", "9.9.9.9")
        assert (ip, source) == ("203.0.113.7", "peer")  # spoofed XFF/CF ignored

    def test_trusted_proxy_walks_chain_right_to_left(self, monkeypatch):
        _config(monkeypatch, cidrs=("10.0.0.0/8",))
        from services.ingestion.context_enricher import resolve_client_ip

        ip, source = resolve_client_ip(
            "10.0.0.5", "198.51.100.9, 10.0.0.3, 10.0.0.4", None
        )
        assert (ip, source) == ("198.51.100.9", "forwarded_chain")

    def test_client_prepended_garbage_not_trusted(self, monkeypatch):
        # A malicious client sends its own XFF; only hops behind trusted
        # proxies count, so the attacker-controlled left side is never reached
        # past the first untrusted hop.
        _config(monkeypatch, cidrs=("10.0.0.0/8",))
        from services.ingestion.context_enricher import resolve_client_ip

        ip, _ = resolve_client_ip("10.0.0.5", "1.2.3.4, 198.51.100.9", None)
        assert ip == "198.51.100.9"  # rightmost untrusted hop wins, not 1.2.3.4

    def test_cloudflare_header_requires_flag_and_trusted_peer(self, monkeypatch):
        from services.ingestion.context_enricher import resolve_client_ip

        _config(monkeypatch, cidrs=("103.21.244.0/22",), cloudflare=True)
        ip, source = resolve_client_ip("103.21.244.1", None, "198.51.100.77")
        assert (ip, source) == ("198.51.100.77", "cloudflare")

        _config(monkeypatch, cidrs=("103.21.244.0/22",), cloudflare=False)
        ip, source = resolve_client_ip("103.21.244.1", None, "198.51.100.77")
        assert source != "cloudflare"

    def test_malformed_chain_falls_back_safely(self, monkeypatch):
        _config(monkeypatch, cidrs=("10.0.0.0/8",))
        from services.ingestion.context_enricher import resolve_client_ip

        ip, source = resolve_client_ip("10.0.0.5", "<script>, junk", None)
        assert (ip, source) == ("10.0.0.5", "peer")


class TestGeoProviders:
    def test_null_provider_is_honestly_not_provisioned(self):
        from services.ingestion.geo_provider import NullGeoProvider

        provider = NullGeoProvider()
        assert provider.capability_state() == "not_provisioned"
        assert provider.lookup("198.51.100.9").state == "not_provisioned"

    def test_private_and_invalid_addresses_classified(self):
        from services.ingestion.geo_provider import NullGeoProvider

        provider = NullGeoProvider()
        assert provider.lookup("10.1.2.3").state == "private_address"
        assert provider.lookup("127.0.0.1").state == "private_address"
        assert provider.lookup("not-an-ip").state == "invalid_address"

    def test_deterministic_provider_serves_fixtures(self):
        from services.ingestion.geo_provider import DeterministicTestGeoProvider, GeoLookup

        provider = DeterministicTestGeoProvider(
            {"198.51.100.9": GeoLookup(state="ready", country_code="US", city="Miami")}
        )
        hit = provider.lookup("198.51.100.9")
        assert (hit.country_code, hit.city) == ("US", "Miami")

    def test_maxmind_fails_closed_without_databases(self, tmp_path):
        from services.ingestion.geo_provider import MaxMindGeoProvider

        provider = MaxMindGeoProvider(
            city_db_path=str(tmp_path / "missing.mmdb"),
            asn_db_path=str(tmp_path / "missing-asn.mmdb"),
        )
        assert provider.capability_state() == "not_provisioned"
        assert provider.lookup("198.51.100.9").state == "not_provisioned"


class TestIpHmac:
    def test_token_is_tenant_scoped_and_rotates(self):
        from shared.privacy.ip_hmac import ip_hmac_token, is_ip_hmac_token

        a = ip_hmac_token("198.51.100.9", "tenant-a", AT)
        b = ip_hmac_token("198.51.100.9", "tenant-b", AT)
        later = ip_hmac_token(
            "198.51.100.9", "tenant-a", parse_instant_strict("2026-07-16T13:00:00Z")
        )
        assert a != b  # no cross-tenant joins
        assert a != later  # rotates across windows
        assert a == ip_hmac_token("198.51.100.9", "tenant-a", AT)  # dedup within window
        assert is_ip_hmac_token(a)
        assert not _IPV4.search(a)  # token never contains the address

    def test_invalid_input_yields_none(self):
        from shared.privacy.ip_hmac import ip_hmac_token

        assert ip_hmac_token(None, "t", AT) is None
        assert ip_hmac_token("garbage", "t", AT) is None


class TestEnrichRequestContext:
    def test_payload_never_contains_raw_ip(self, monkeypatch):
        _config(monkeypatch, cidrs=())
        from services.ingestion.context_enricher import enrich_request_context
        from services.ingestion.geo_provider import DeterministicTestGeoProvider, GeoLookup

        context = enrich_request_context(
            tenant_id="tenant-a",
            at=AT,
            peer_ip="198.51.100.9",
            provider=DeterministicTestGeoProvider(
                {"198.51.100.9": GeoLookup(state="ready", country_code="US", city="Miami")}
            ),
        )
        payload = context.as_payload()
        assert payload["enrichment_state"] == "ready"
        assert payload["country_code"] == "US"
        assert not _IPV4.search(str(payload))  # raw IP structurally absent
        assert payload["ip_token"].startswith("iph1:")

    def test_missing_peer_yields_explicit_state(self, monkeypatch):
        _config(monkeypatch, cidrs=())
        from services.ingestion.context_enricher import enrich_request_context

        context = enrich_request_context(tenant_id="t", at=AT, peer_ip=None)
        assert context.enrichment_state == "no_client_address"
        assert context.ip_token is None


@pytest.mark.asyncio
async def test_batch_hook_disabled_by_default_costs_nothing(monkeypatch):
    import config.settings as settings_module
    from config.settings import ContextIntelligenceConfig
    from services.ingestion import batch

    monkeypatch.setattr(
        settings_module.settings,
        "context_intelligence",
        ContextIntelligenceConfig(enrichment_enabled=False),
    )

    class _Req:
        headers: dict = {}
        client = None

    assert batch._build_server_context(_Req(), "tenant-a") is None
