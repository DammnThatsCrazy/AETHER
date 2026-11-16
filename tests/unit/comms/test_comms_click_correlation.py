"""Signed email click token → landing touchpoint → recipient profile.

A campaign link carries ``?ae=<signed token>``. The Web SDK forwards it as
``clickToken``; the Silver dispatcher must verify it for the event's tenant,
strip it from every URL, stamp the campaign/message/link lineage on the
touchpoint, and attribute the anonymous visit to the recipient — unless the
visitor is already a different known person (a forwarded link).
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "services" / "api"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")

TENANT = "tenant-a"
CAMPAIGN = "f113dca1-8b82-4d94-ac2a-c111a6e44c09"
ALIAS = "alias-hash-recipient"
RECIPIENT = "entity-recipient"


def _token(tenant: str = TENANT, *, alias: str | None = ALIAS) -> str:
    from journeys.comms.click_token import issue_click_token

    return issue_click_token(
        tenant,
        campaign_id=CAMPAIGN,
        external_message_id="msg-65",
        recipient_alias_id=alias,
        link_id="link-cta",
        sequence_step=1,
    )


def _page_event(token: str, *, user_id: str | None = None, anon: str = "anon-1") -> dict:
    return {
        "type": "page",
        "messageId": f"evt-{anon}-{user_id}",
        "anonymousId": anon,
        "userId": user_id,
        "timestamp": "2026-11-16T12:00:00Z",
        "context": {
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
        },
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
    blob = repr(ctx)
    assert token not in blob
    assert "utm_source=email" in ctx["page"]["url"]
    assert "verifiedClick" not in ctx["trafficSource"]


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


@pytest.mark.asyncio
class TestDispatcherCorrelation:
    async def test_anonymous_visit_is_attributed_to_recipient(self, monkeypatch):
        _identity(monkeypatch, {("email_hash", ALIAS): RECIPIENT})
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
        assert row["provenance"]["click_correlation"]["recipient_outcome"] == "resolved"

    async def test_forwarded_link_never_reassigns_identity(self, monkeypatch):
        from identity.identity.normalization import normalize_anonymous_id

        _identity(monkeypatch, {
            ("email_hash", ALIAS): RECIPIENT,
            ("anonymous_id", normalize_anonymous_id("anon-friend", TENANT)): "entity-friend",
        })
        token = _token()
        row = await _project(monkeypatch, _page_event(token, anon="anon-friend"))

        assert row["profile_id"] is None
        assert row["identity_resolution_method"] == "forwarded_link"
        assert row["identity_confidence"] == pytest.approx(0.4)
        assert row["link_id"] == "link-cta"  # campaign lineage still recorded
        assert row["provenance"]["click_correlation"]["recipient_outcome"] == "forwarded"

    async def test_authenticated_recipient_keeps_own_profile(self, monkeypatch):
        from identity.identity.normalization import normalize_user_id

        _identity(monkeypatch, {
            ("email_hash", ALIAS): RECIPIENT,
            ("user_id", normalize_user_id("u-42", TENANT)): RECIPIENT,
        })
        row = await _project(monkeypatch, _page_event(_token(), user_id="u-42"))
        assert row["profile_id"] == "u-42"
        assert row["identity_resolution_method"] == "signed_click"

    async def test_unresolved_alias_records_lineage_only(self, monkeypatch):
        _identity(monkeypatch, {})
        row = await _project(monkeypatch, _page_event(_token()))
        assert row["profile_id"] is None
        assert row["identity_resolution_method"] is None
        assert row["external_message_id"] == "msg-65"
        assert row["provenance"]["click_correlation"]["recipient_outcome"] == "unresolved"

    async def test_cross_tenant_token_is_stripped_and_ignored(self, monkeypatch):
        _identity(monkeypatch, {("email_hash", ALIAS): RECIPIENT})
        token = _token("tenant-b")
        event = _page_event(token)
        row = await _project(monkeypatch, event)

        _assert_token_stripped(event, token)
        assert row["profile_id"] is None
        assert row["link_id"] is None
        assert row["_campaign_hint_seen"] is None
        assert "click_correlation" not in row["provenance"]

    async def test_forged_claim_without_token_is_dropped(self, monkeypatch):
        _identity(monkeypatch, {})
        event = _page_event("")
        event["context"]["_verified_click"] = {"recipient_entity_id": "forged"}
        event["_verified_click"] = {"recipient_entity_id": "forged", "identity_method": "signed_click"}
        row = await _project(monkeypatch, event)
        assert row["profile_id"] is None
        assert row["identity_resolution_method"] is None


@pytest.mark.asyncio
class TestUniqueEntityResolution:
    async def test_ambiguous_alias_is_rejected(self):
        from journeys.comms.identity_bridge import resolve_unique_tenant_entity_for_alias

        class Aliases:
            async def find_subjects_by_alias(self, *_a):
                return ["e1", "e2"]

        assert await resolve_unique_tenant_entity_for_alias(
            TENANT, "email_hash", ALIAS, alias_repository=Aliases(), entity_repository=object()
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
            TENANT, "email_hash", ALIAS, alias_repository=Aliases(), entity_repository=Entities("tenant-b")
        ) is None
        assert await resolve_unique_tenant_entity_for_alias(
            TENANT, "email_hash", ALIAS, alias_repository=Aliases(), entity_repository=Entities(TENANT)
        ) == "e1"
