"""Signed email click token → landing touchpoint → recipient identity.

A campaign link carries ``?ae=<signed token>``. The Web SDK forwards it as
``context.trafficSource.clickToken``. At the authenticated ingestion boundary
the token is verified and replaced by a seal bound to that one event, so the
reusable link token never reaches Bronze. The Silver dispatcher and the
identity worker open the seal and apply one shared decision:

* identity-stitching consent is required (same rule as observed emails);
* the first browser to present a token is bound to it; another browser that
  presents the same token later is a forwarded link;
* a visitor already known as a different person is a forwarded link;
* otherwise the visit is the recipient's — attributed on the touchpoint when
  the alias maps to one entity, and linked through identity resolution even
  when it does not yet (so a later signup with that email merges).
"""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "services" / "api"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("AETHER_ENV", "local")

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")

TENANT = "tenant-a"
CAMPAIGN = "f113dca1-8b82-4d94-ac2a-c111a6e44c09"
RECIPIENT = "entity-recipient"
CONSENT = {"analytics": True, "marketing": False, "policyVersion": "2026-09"}


def _alias(email: str = "jane@example.com", tenant: str = TENANT) -> str:
    from journeys.comms.mailbox import build_email_alias

    return build_email_alias(email, tenant).alias_hash


def _token(tenant: str = TENANT, *, alias: str | None = None, link: str = "link-cta") -> str:
    from journeys.comms.click_token import issue_click_token

    return issue_click_token(
        tenant,
        campaign_id=CAMPAIGN,
        external_message_id="msg-65",
        recipient_alias_id=_alias(tenant=tenant) if alias is None else alias,
        link_id=link,
        sequence_step=1,
    )


class FakeCache:
    def __init__(self, *, broken: bool = False) -> None:
        self.data: dict[str, str] = {}
        self.broken = broken

    async def set_nx(self, key, value, ttl=0):
        if self.broken:
            raise ConnectionError("cache down")
        if key in self.data:
            return False
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)


@pytest.fixture
def cache(monkeypatch):
    fake = FakeCache()
    import dependencies.providers as providers

    monkeypatch.setattr(providers, "get_cache", lambda: fake)
    return fake


def _page_event(
    token: str, *, user_id: str | None = None, anon: str = "anon-1", consent=CONSENT,
    message_id: str | None = None,
) -> dict:
    context = {
        "tenantId": TENANT,
        "trafficSource": {
            "clickToken": token,
            "landingPage": f"https://shop.test/sale?utm_source=email&ae={token}",
            "verifiedClick": {"recipient_entity_id": "forged"},
        },
        "page": {
            "url": f"https://shop.test/sale?utm_source=email&ae={token}",
            "search": f"?utm_source=email&ae={token}",
        },
    }
    if consent is not None:
        context["consent"] = consent
    return {
        "type": "page",
        "messageId": message_id or f"evt-{anon}-{user_id}",
        "anonymousId": anon,
        "userId": user_id,
        "timestamp": "2026-11-16T12:00:00Z",
        "context": context,
        "properties": {},
    }


def _identity(monkeypatch, bindings: dict[tuple[str, str], str]) -> None:
    """Fake identity store: (alias_type, normalized hash) → entity."""
    from journeys.comms import identity_bridge

    async def fake(tenant_id, alias_type, alias_hash, **_kw):
        if tenant_id != TENANT:
            return None
        return bindings.get((getattr(alias_type, "value", alias_type), alias_hash))

    monkeypatch.setattr(identity_bridge, "resolve_unique_tenant_entity_for_alias", fake)


async def _project(monkeypatch, event: dict) -> dict:
    from ingestion.silver import dispatcher as dispatcher_module
    from ingestion.silver.dispatcher import SilverDispatcher
    from ingestion.silver.projectors.touchpoint_projector import TouchpointProjector

    projector = TouchpointProjector()
    captured: list[dict] = []

    async def resolve_campaign(rows, *, table):
        captured.append({"hint": rows[0].get("_canonical_campaign_id_hint")})
        for row in rows:
            row.pop("_canonical_campaign_id_hint", None)
            row.pop("_utm_id", None)

    async def no_op(*_a, **_k):
        return None

    monkeypatch.setitem(dispatcher_module._TYPE_MAP, "page", [projector])
    monkeypatch.setattr(dispatcher_module, "_resolve_campaign_rows", resolve_campaign)
    monkeypatch.setattr(dispatcher_module, "_shadow_compare_touchpoints", no_op)
    monkeypatch.setattr(dispatcher_module._graph_projector, "maybe_emit", no_op)
    monkeypatch.setattr(dispatcher_module._capability_catalog, "maybe_record", no_op)
    monkeypatch.setattr(projector, "_emit_to_canonical_activity", no_op)

    results = await SilverDispatcher().project(event)
    rows = [r for res in results for r in (res.rows or [])]
    assert len(rows) == 1
    row = deepcopy(rows[0])
    row["_campaign_hint_seen"] = captured[0]["hint"] if captured else None
    return row


def _assert_token_stripped(event: dict, token: str) -> None:
    ctx = event["context"]
    assert token not in repr(ctx)
    assert "utm_source=email" in ctx["page"]["url"]
    assert "verifiedClick" not in ctx["trafficSource"]


def _outcome(row: dict) -> str:
    return row["provenance"]["click_correlation"]["recipient_outcome"]


class TestUrlHandling:
    def test_strips_only_token_shaped_ae(self):
        from journeys.comms.click_token import strip_click_token_from_url

        token = _token()
        assert strip_click_token_from_url(f"https://x.test/p?a=1&ae={token}") == "https://x.test/p?a=1"
        assert strip_click_token_from_url(f"?ae={token}") == ""
        # A tenant's own unrelated ``ae`` parameter is left untouched.
        assert strip_click_token_from_url("https://x.test/p?ae=checkout") == "https://x.test/p?ae=checkout"

    def test_extracts_from_url_when_typed_field_missing(self):
        from journeys.comms.click_token import extract_and_strip_click_token

        token = _token()
        event = {"context": {"page": {"url": f"https://x.test/p?ae={token}"}}}
        assert extract_and_strip_click_token(event) == token
        assert event["context"]["page"]["url"] == "https://x.test/p"


class TestPersistenceBoundary:
    def _sdk_event(self, token: str, event_id: str = "evt-boundary"):
        from ingestion.ingestion.batch import BaseEvent

        return BaseEvent(
            id=event_id,
            type="page",
            timestamp="2026-11-16T12:00:00Z",
            sessionId="sess-1",
            anonymousId="anon-1",
            properties={"url": f"https://shop.test/sale?ae={token}"},
            context={
                "library": {"name": "@olympuslabs/aether-web", "version": "9.1.0"},
                "consent": CONSENT,
                "surface": "web",
                "trafficSource": {
                    "clickToken": token,
                    "landingPage": f"https://shop.test/sale?ae={token}",
                },
                "page": {"url": f"https://shop.test/sale?ae={token}"},
            },
        )

    def test_normalized_payload_carries_seal_not_token(self):
        from ingestion.ingestion.validation import build_normalized_payload
        from journeys.comms.click_token import open_click_seal

        token = _token()
        payload = build_normalized_payload(self._sdk_event(token), TENANT, "b1", "2026-11-16T12:00:01Z")

        assert token not in repr(payload)
        claims = open_click_seal(payload["verified_click"], TENANT, "evt-boundary")
        assert claims is not None and claims.link_id == "link-cta"
        # The seal is bound to its event and tenant: it cannot be replayed.
        assert open_click_seal(payload["verified_click"], TENANT, "evt-other") is None
        assert open_click_seal(payload["verified_click"], "tenant-b", "evt-boundary") is None

    def test_cross_tenant_token_is_dropped_without_seal(self):
        from ingestion.ingestion.validation import build_normalized_payload

        token = _token("tenant-b")
        payload = build_normalized_payload(self._sdk_event(token), TENANT, "b1", "2026-11-16T12:00:01Z")
        assert token not in repr(payload)
        assert "verified_click" not in payload

    def test_bronze_sanitizer_scrubs_any_raw_token(self):
        from ingestion.ingestion.acquisition_privacy import sanitize_acquisition_payload

        token = _token()
        dirty = {
            "context": {"trafficSource": {"clickToken": token}, "page": {"url": f"https://x.test/?ae={token}"}},
            "properties": {"nested": [{"href": f"https://x.test/a?b=1&ae={token}"}]},
        }
        clean = sanitize_acquisition_payload(dirty)
        assert token not in repr(clean)
        assert clean["properties"]["nested"][0]["href"] == "https://x.test/a?b=1"


@pytest.mark.asyncio
class TestDispatcherCorrelation:
    async def test_anonymous_visit_is_attributed_to_recipient(self, monkeypatch, cache):
        _identity(monkeypatch, {("email_hash", _alias()): RECIPIENT})
        token = _token()
        event = _page_event(token)
        row = await _project(monkeypatch, event)

        _assert_token_stripped(event, token)
        assert token not in (row["landing_url"] or "")
        assert row["profile_id"] == RECIPIENT
        assert row["anonymous_id"] == "anon-1"
        assert row["identity_resolution_method"] == "signed_click"
        assert row["identity_confidence"] == pytest.approx(0.9)
        assert row["external_message_id"] == "msg-65"
        assert row["link_id"] == "link-cta"
        assert row["sequence_step"] == 1
        assert row["_campaign_hint_seen"] == CAMPAIGN
        assert _outcome(row) == "resolved"

    async def test_sealed_envelope_from_ingestion_is_honoured(self, monkeypatch, cache):
        from journeys.comms.click_token import seal_click_claims, verify_click_token

        _identity(monkeypatch, {("email_hash", _alias()): RECIPIENT})
        claims = verify_click_token(_token(), TENANT).claims
        event = _page_event("", message_id="evt-sealed")
        event["verified_click"] = seal_click_claims(claims, TENANT, "evt-sealed")
        row = await _project(monkeypatch, event)
        assert row["profile_id"] == RECIPIENT
        assert "verified_click" not in event

    async def test_seal_for_another_event_is_rejected(self, monkeypatch, cache):
        from journeys.comms.click_token import seal_click_claims, verify_click_token

        _identity(monkeypatch, {("email_hash", _alias()): RECIPIENT})
        claims = verify_click_token(_token(), TENANT).claims
        event = _page_event("", message_id="evt-replay")
        event["verified_click"] = seal_click_claims(claims, TENANT, "evt-original")
        row = await _project(monkeypatch, event)
        assert row["profile_id"] is None
        assert "click_correlation" not in row["provenance"]

    async def test_second_browser_with_same_link_is_forwarded(self, monkeypatch, cache):
        _identity(monkeypatch, {("email_hash", _alias()): RECIPIENT})
        token = _token()
        first = await _project(monkeypatch, _page_event(token, anon="anon-recipient"))
        again = await _project(monkeypatch, _page_event(token, anon="anon-recipient"))
        other = await _project(monkeypatch, _page_event(token, anon="anon-friend"))

        assert first["profile_id"] == again["profile_id"] == RECIPIENT
        assert other["profile_id"] is None
        assert other["identity_resolution_method"] == "forwarded_link"
        assert other["identity_confidence"] == pytest.approx(0.4)
        assert other["link_id"] == "link-cta"  # campaign lineage still recorded
        assert _outcome(other) == "forwarded"

    async def test_known_different_visitor_is_forwarded(self, monkeypatch, cache):
        from identity.identity.normalization import normalize_anonymous_id

        _identity(monkeypatch, {
            ("email_hash", _alias()): RECIPIENT,
            ("anonymous_id", normalize_anonymous_id("anon-friend", TENANT)): "entity-friend",
        })
        row = await _project(monkeypatch, _page_event(_token(), anon="anon-friend"))
        assert row["profile_id"] is None
        assert _outcome(row) == "forwarded"

    async def test_authenticated_recipient_keeps_own_profile(self, monkeypatch, cache):
        from identity.identity.normalization import normalize_user_id

        _identity(monkeypatch, {
            ("email_hash", _alias()): RECIPIENT,
            ("user_id", normalize_user_id("u-42", TENANT)): RECIPIENT,
        })
        row = await _project(monkeypatch, _page_event(_token(), user_id="u-42"))
        assert row["profile_id"] == "u-42"
        assert row["identity_resolution_method"] == "signed_click"

    async def test_without_consent_only_lineage_is_recorded(self, monkeypatch, cache):
        _identity(monkeypatch, {("email_hash", _alias()): RECIPIENT})
        row = await _project(monkeypatch, _page_event(_token(), consent={"analytics": False}))
        assert row["profile_id"] is None
        assert row["identity_resolution_method"] is None
        assert row["link_id"] == "link-cta"
        assert _outcome(row) == "consent_required"
        assert cache.data == {}  # no binding is written without consent

    async def test_cache_outage_fails_closed(self, monkeypatch):
        import dependencies.providers as providers

        monkeypatch.setattr(providers, "get_cache", lambda: FakeCache(broken=True))
        _identity(monkeypatch, {("email_hash", _alias()): RECIPIENT})
        row = await _project(monkeypatch, _page_event(_token()))
        assert row["profile_id"] is None
        assert _outcome(row) == "binding_unavailable"

    async def test_unresolved_alias_records_lineage_only(self, monkeypatch, cache):
        _identity(monkeypatch, {})
        row = await _project(monkeypatch, _page_event(_token()))
        assert row["profile_id"] is None
        assert row["identity_resolution_method"] is None
        assert row["external_message_id"] == "msg-65"
        assert _outcome(row) == "unresolved"

    async def test_cross_tenant_token_is_stripped_and_ignored(self, monkeypatch, cache):
        _identity(monkeypatch, {("email_hash", _alias()): RECIPIENT})
        token = _token("tenant-b")
        event = _page_event(token)
        row = await _project(monkeypatch, event)

        _assert_token_stripped(event, token)
        assert row["profile_id"] is None
        assert row["link_id"] is None
        assert row["_campaign_hint_seen"] is None
        assert "click_correlation" not in row["provenance"]

    async def test_forged_claim_without_token_is_dropped(self, monkeypatch, cache):
        _identity(monkeypatch, {})
        event = _page_event("")
        event["_verified_click"] = {"recipient_entity_id": "forged", "identity_method": "signed_click"}
        event["verified_click"] = {"v": "1", "p": "e30", "sig": "forged-signature-value"}
        row = await _project(monkeypatch, event)
        assert row["profile_id"] is None
        assert row["identity_resolution_method"] is None


@pytest.mark.asyncio
class TestIdentityStitching:
    def _payload(self, *, anon: str, event_id: str, consent=CONSENT, token: str | None = None) -> dict:
        from journeys.comms.click_token import seal_click_claims, verify_click_token

        claims = verify_click_token(token or _token(), TENANT).claims
        return {
            "event_id": event_id,
            "tenant_id": TENANT,
            "anonymous_id": anon,
            "context": {"consent": consent},
            "verified_click": seal_click_claims(claims, TENANT, event_id),
        }

    async def test_first_browser_gets_recipient_email_signal(self, monkeypatch, cache):
        from journeys.comms.click_token import identity_signals_for_click

        _identity(monkeypatch, {})
        signals = await identity_signals_for_click(
            self._payload(anon="anon-1", event_id="e1"), tenant_id=TENANT
        )
        assert signals == [{"type": "email_hash", "hash": _alias(), "source": "signed_click"}]

    async def test_forwarded_browser_and_unconsented_get_nothing(self, monkeypatch, cache):
        from journeys.comms.click_token import identity_signals_for_click

        _identity(monkeypatch, {})
        token = _token()
        await identity_signals_for_click(
            self._payload(anon="anon-1", event_id="e1", token=token), tenant_id=TENANT
        )
        assert await identity_signals_for_click(
            self._payload(anon="anon-friend", event_id="e2", token=token), tenant_id=TENANT
        ) == []
        assert await identity_signals_for_click(
            self._payload(anon="anon-3", event_id="e3", consent={"analytics": False}), tenant_id=TENANT
        ) == []

    async def test_seal_from_another_tenant_gets_nothing(self, monkeypatch, cache):
        from journeys.comms.click_token import identity_signals_for_click

        assert await identity_signals_for_click(
            self._payload(anon="anon-1", event_id="e1"), tenant_id="tenant-b"
        ) == []


class TestResolverServerSignals:
    @pytest.fixture(autouse=True)
    def _identity_on(self, monkeypatch):
        from dataclasses import replace

        from config.settings import settings

        monkeypatch.setattr(settings, "identity_continuity", replace(
            settings.identity_continuity, resolution_enabled=True, auto_merge_enabled=True,
        ))

    def test_only_tenant_email_hashes_are_accepted(self):
        from identity.identity.resolver import _server_alias_signals

        good = "a" * 64
        event = {"_server_alias_signals": [
            {"type": "email_hash", "hash": good, "source": "signed_click"},
            {"type": "user_id", "hash": good},
            {"type": "email_hash", "hash": "not-a-hash"},
            "junk",
        ]}
        assert _server_alias_signals(event) == [
            {"hash": good, "display": "email:signed_click", "source": "signed_click"}
        ]
        assert _server_alias_signals({}) == []

    @pytest.mark.asyncio
    async def test_clicked_visitor_merges_with_later_signup(self):
        from identity.identity.audit import IdentityAuditWriter
        from identity.identity.conflicts import IdentityConflictManager
        from identity.identity.graph_writer import IdentityGraphWriter
        from identity.identity.metrics import IdentityMetrics
        from identity.identity.models import IdentitySignalType
        from identity.identity.repository import IdentityResolutionRepository
        from identity.identity.resolver import IdentityResolutionService
        from repositories.repos import reset_in_memory_stores

        reset_in_memory_stores()
        repo = IdentityResolutionRepository()
        metrics = IdentityMetrics()
        resolver = IdentityResolutionService(
            repo=repo, graph_writer=IdentityGraphWriter(repo, metrics),
            audit_writer=IdentityAuditWriter(repo),
            conflict_manager=IdentityConflictManager(repo), metrics=metrics,
        )
        alias = _alias()
        click = await resolver.resolve_event({
            "event_id": "evt-click", "tenant_id": TENANT, "anonymous_id": "anon-click",
            "context": {"consent": CONSENT}, "properties": {},
            "_server_alias_signals": [{"type": "email_hash", "hash": alias, "source": "signed_click"}],
        }, TENANT)
        assert click.canonical_entity_id
        holders = await repo.find_subjects_by_alias(TENANT, IdentitySignalType.EMAIL_HASH, alias)
        assert holders == [click.canonical_entity_id]

        signup = await resolver.resolve_event({
            "event_id": "evt-signup", "tenant_id": TENANT, "anonymous_id": "anon-laptop",
            "user_id": "u-jane", "context": {"consent": CONSENT},
            "properties": {"email": "Jane@Example.com"},
        }, TENANT)
        survivor_click = await repo.resolve_surviving_canonical_entity_id(TENANT, click.canonical_entity_id)
        survivor_signup = await repo.resolve_surviving_canonical_entity_id(TENANT, signup.canonical_entity_id)
        assert survivor_click == survivor_signup
        reset_in_memory_stores()

    @pytest.mark.asyncio
    async def test_server_signal_needs_consent_to_become_an_alias(self):
        from identity.identity.audit import IdentityAuditWriter
        from identity.identity.conflicts import IdentityConflictManager
        from identity.identity.graph_writer import IdentityGraphWriter
        from identity.identity.metrics import IdentityMetrics
        from identity.identity.models import IdentitySignalType
        from identity.identity.repository import IdentityResolutionRepository
        from identity.identity.resolver import IdentityResolutionService
        from repositories.repos import reset_in_memory_stores

        reset_in_memory_stores()
        repo = IdentityResolutionRepository()
        metrics = IdentityMetrics()
        resolver = IdentityResolutionService(
            repo=repo, graph_writer=IdentityGraphWriter(repo, metrics),
            audit_writer=IdentityAuditWriter(repo),
            conflict_manager=IdentityConflictManager(repo), metrics=metrics,
        )
        alias = _alias()
        await resolver.resolve_event({
            "event_id": "evt-click", "tenant_id": TENANT, "anonymous_id": "anon-click",
            "context": {"consent": {"analytics": False}}, "properties": {},
            "_server_alias_signals": [{"type": "email_hash", "hash": alias, "source": "signed_click"}],
        }, TENANT)
        assert await repo.find_subjects_by_alias(TENANT, IdentitySignalType.EMAIL_HASH, alias) == []
        reset_in_memory_stores()


@pytest.mark.asyncio
class TestUniqueEntityResolution:
    async def test_ambiguous_alias_is_rejected(self):
        from journeys.comms.identity_bridge import resolve_unique_tenant_entity_for_alias

        class Aliases:
            async def find_subjects_by_alias(self, *_a):
                return ["e1", "e2"]

        assert await resolve_unique_tenant_entity_for_alias(
            TENANT, "email_hash", "a" * 64, alias_repository=Aliases(), entity_repository=object()
        ) is None

    async def test_other_tenant_entity_is_rejected(self):
        from journeys.comms.identity_bridge import resolve_unique_tenant_entity_for_alias

        class Aliases:
            async def find_subjects_by_alias(self, *_a):
                return ["e1"]

        class Entities:
            def __init__(self, tenant):
                self.tenant = tenant

            async def find_by_id(self, entity_id):
                return {"entity_id": entity_id, "tenant_id": self.tenant}

        assert await resolve_unique_tenant_entity_for_alias(
            TENANT, "email_hash", "a" * 64, alias_repository=Aliases(), entity_repository=Entities("tenant-b")
        ) is None
        assert await resolve_unique_tenant_entity_for_alias(
            TENANT, "email_hash", "a" * 64, alias_repository=Aliases(), entity_repository=Entities(TENANT)
        ) == "e1"
