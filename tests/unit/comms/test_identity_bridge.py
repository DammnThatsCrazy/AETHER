"""Provider identity bridge (§13) — resolution, provisional preservation,
shared-mailbox safety, idempotency, and merge repointing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


@pytest.fixture(autouse=True)
def _clean():
    from repositories.repos import _IN_MEMORY_STORES
    _IN_MEMORY_STORES.clear()
    yield
    _IN_MEMORY_STORES.clear()


@pytest.mark.asyncio
async def test_personal_email_records_provisional_with_alias():
    from services.comms.identity_bridge import ProviderIdentityBridge

    bridge = ProviderIdentityBridge()
    ident = await bridge.record_observation(
        tenant_id="t1", provider="klaviyo", provider_account_id="acct-1",
        provider_profile_id="kl-prof-1", raw_email="jane.doe@example.com",
    )
    assert ident is not None
    assert ident.resolution_status == "provisional"   # no canonical entity in local
    assert ident.email_alias_hash and "@" not in ident.email_alias_hash  # hashed, no PII
    assert ident.is_shared_mailbox is False
    assert ident.confidence > 0


@pytest.mark.asyncio
async def test_shared_mailbox_never_auto_resolves_to_human(monkeypatch):
    from services.comms.identity_bridge import ProviderIdentityBridge

    # Even if an entity exists for the alias, a shared mailbox must not collapse.
    async def fake_resolve(self, tenant_id, alias_hash):
        return "entity-should-not-be-used"

    monkeypatch.setattr(ProviderIdentityBridge, "_resolve_entity_by_alias", fake_resolve)
    bridge = ProviderIdentityBridge()
    ident = await bridge.record_observation(
        tenant_id="t1", provider="klaviyo", provider_account_id="acct-1",
        provider_profile_id="kl-prof-shared", raw_email="support@example.com",
    )
    assert ident.is_shared_mailbox is True
    assert ident.resolution_status == "provisional"
    assert ident.canonical_entity_id is None


@pytest.mark.asyncio
async def test_resolves_when_alias_maps_to_entity(monkeypatch):
    from services.comms.identity_bridge import ProviderIdentityBridge

    async def fake_resolve(self, tenant_id, alias_hash):
        return "entity-42"

    monkeypatch.setattr(ProviderIdentityBridge, "_resolve_entity_by_alias", fake_resolve)
    bridge = ProviderIdentityBridge()
    ident = await bridge.record_observation(
        tenant_id="t1", provider="klaviyo", provider_account_id="acct-1",
        provider_profile_id="kl-prof-2", raw_email="john@example.com",
    )
    assert ident.resolution_status == "resolved"
    assert ident.canonical_entity_id == "entity-42"
    assert ident.resolution_method == "email_alias"
    assert ident.verified_at is not None


@pytest.mark.asyncio
async def test_observation_is_idempotent_and_preserves_first_seen():
    from services.comms.identity_bridge import ProviderIdentityBridge, ProviderIdentityRepository

    bridge = ProviderIdentityBridge()
    first = await bridge.record_observation(
        tenant_id="t1", provider="klaviyo", provider_account_id="acct-1",
        provider_profile_id="kl-prof-3", raw_email="a@example.com",
    )
    again = await bridge.record_observation(
        tenant_id="t1", provider="klaviyo", provider_account_id="acct-1",
        provider_profile_id="kl-prof-3", raw_email="a@example.com",
    )
    assert first.identity_id == again.identity_id
    provisional = await ProviderIdentityRepository().list_provisional("t1")
    assert len(provisional) == 1  # one row, not two


@pytest.mark.asyncio
async def test_record_identity_from_profile_event():
    from services.comms.identity_bridge import record_identity_from_event, ProviderIdentityRepository

    ident = await record_identity_from_event("t1", {
        "event_type": "klaviyo.profile",
        "source": "klaviyo",
        "properties": {
            "provider": "klaviyo", "provider_account_id": "acct-1",
            "provider_profile_id": "kl-prof-9", "email": "person@example.com",
        },
    })
    assert ident is not None and ident.provider_profile_id == "kl-prof-9"
    rows = await ProviderIdentityRepository().list_provisional("t1")
    assert any(r["provider_profile_id"] == "kl-prof-9" for r in rows)


@pytest.mark.asyncio
async def test_merge_repoints_mappings():
    from services.comms.identity_bridge import ProviderIdentityBridge, ProviderIdentityRepository

    bridge = ProviderIdentityBridge()
    row = await bridge.record_observation(
        tenant_id="t1", provider="klaviyo", provider_account_id="acct-1",
        provider_profile_id="kl-prof-m", raw_email="m@example.com",
        canonical_entity_id="entity-old",
    )
    assert row.canonical_entity_id == "entity-old"

    moved = await bridge.on_identity_merge("t1", "entity-old", "entity-new")
    assert moved == 1
    rows = await ProviderIdentityRepository().list_for_entity("t1", "entity-new")
    assert len(rows) == 1 and rows[0]["resolution_method"] == "identity_merge"
