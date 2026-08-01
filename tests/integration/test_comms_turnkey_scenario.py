"""Credential-turnkey end-to-end scenario (permanent CI fixture, §26/§27).

Companion to test_comms_golden_scenario.py. Where the golden fixture proves the
projection/funnel/graph vertical slice, this proves the credential-turnkey
spine end to end through the REAL connector sync + ingest path:

  connector configured → credential stored → sync started → durable sync-run
  recorded → provider events ingested → provider identity bridged (provisional
  + resolvable) → unsubscribe → canonical suppression → usage metered (dedupe-
  safe) → suppression reconciliation.

No live provider call (the pull is stubbed); no synthetic runtime data.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")

TENANT = "tenant-turnkey"
PROVIDER = "klaviyo"


@pytest.fixture(autouse=True)
def _clean():
    from repositories.repos import _IN_MEMORY_STORES
    from services.comms.repository import _local_suppressions
    _IN_MEMORY_STORES.clear()
    _local_suppressions.clear()
    yield
    _IN_MEMORY_STORES.clear()
    _local_suppressions.clear()


@pytest.mark.asyncio
async def test_credential_turnkey_scenario(monkeypatch):
    from services.integrations.connectors.service import connector_service
    from services.integrations.connectors.klaviyo import KlaviyoConnector
    from services.integrations.connectors.base import NormalizedEvent
    from services.comms.sync_runs import SyncRunService
    from services.comms.identity_bridge import ProviderIdentityBridge, ProviderIdentityRepository
    from services.comms.suppression_authority import SuppressionAuthorityService
    from services.metering_evidence.service import MeteringEvidenceRepository

    # ── Stubbed provider pull: a campaign catalog record + lifecycle events ──
    def _event(etype: str, ext: str, props: dict) -> NormalizedEvent:
        return NormalizedEvent(
            event_type=etype, source=PROVIDER, external_id=ext,
            properties={"provider": PROVIDER, "provider_account_id": "acct-1", **props},
        )

    async def fake_pull(self, config, since=None, secret=None):
        return [
            _event("klaviyo.campaign", "camp-1", {
                "external_campaign_id": "camp-1", "name": "Welcome", "channel": "email",
            }),
            _event("email_sent", "s-1", {
                "recipient_email": "customer@example.com", "provider_profile_id": "pf-1",
                "external_campaign_id": "camp-1",
            }),
            _event("email_replied", "r-1", {
                "recipient_email": "customer@example.com", "provider_profile_id": "pf-1",
                "direction": "inbound",
            }),
            _event("unsubscribe_observed", "u-1", {
                "recipient_email": "customer@example.com", "provider_profile_id": "pf-1",
                "unsubscribe_scope": "marketing_channel",
            }),
        ]

    monkeypatch.setattr(KlaviyoConnector, "pull", fake_pull)

    # ── 1. Configure + credential + sync (customer-initiated, no operator) ───
    await connector_service.configure(
        TENANT, PROVIDER, name="Klaviyo", enabled=True,
        credential="pk_live_stub", actor_id="customer-admin",
    )
    result = await connector_service.sync(TENANT, PROVIDER, actor_id="customer-admin",
                                          since="2026-06-01T00:00:00+00:00")
    assert result.status == "healthy"

    # ── 2. Durable sync-run recorded with honest counts (§12.4) ──────────────
    runs = await SyncRunService().list_for_connector(
        TENANT, (await connector_service.get(TENANT, PROVIDER))["config_id"])
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "completed"
    assert run["mode"] == "incremental"  # since given
    assert run["records_received"] == 4
    assert run["replies_correlated"] == 1
    assert run["suppressions_updated"] == 1
    assert run["cursor_after"] is not None

    # ── 3. Provider identity bridged (provisional; no PII stored) ────────────
    provisional = await ProviderIdentityRepository().list_provisional(TENANT)
    assert any(p["provider_profile_id"] == "pf-1" for p in provisional)
    for p in provisional:
        assert not p.get("email_alias_hash") or "@" not in p["email_alias_hash"]

    # ── 3b. Identity resolves to a canonical entity on later evidence ────────
    async def fake_resolve(self, tenant_id, alias_hash):
        return "entity-77"
    monkeypatch.setattr(ProviderIdentityBridge, "_resolve_entity_by_alias", fake_resolve)
    resolved = await ProviderIdentityBridge().record_observation(
        tenant_id=TENANT, provider=PROVIDER, provider_account_id="acct-1",
        provider_profile_id="pf-1", raw_email="customer@example.com",
    )
    assert resolved.resolution_status == "resolved"
    assert resolved.canonical_entity_id == "entity-77"

    # ── 4. Canonical suppression recorded + fail-closed enforcement (§16) ────
    supp = SuppressionAuthorityService()
    active = await supp.list_for_tenant(TENANT)
    assert any(s["reason"] == "unsubscribe" for s in active)
    alias = active[0]["recipient_alias_id"]
    assert await supp.is_suppressed(TENANT, recipient_alias_id=alias) is True
    # Observe-only: provider-reported, write-back disabled.
    assert active[0]["provider_enforcement_state"] == "provider_reported"
    assert active[0]["aether_enforcement_state"] == "write_back_disabled"

    # ── 5. Usage metered, dedupe-safe (§20) ──────────────────────────────────
    meter = MeteringEvidenceRepository()
    events = await meter.find_many({"tenant_id": TENANT, "usage_dimension": "comms_events"})
    replies = await meter.find_many({"tenant_id": TENANT, "usage_dimension": "comms_reply_events"})
    assert len(events) == 3          # sent + replied + unsubscribe (3 comm events)
    assert len(replies) == 1         # the reply, on its own dimension
    assert all(e.get("billable") for e in events)  # first sighting of each → billable

    # ── 6. Reconciliation is observe-only and reports drift honestly ─────────
    recon = await supp.reconcile(TENANT, provider=PROVIDER, provider_reported=[
        {"recipient_alias_id": alias},
        {"recipient_alias_id": "someone_else"},
    ])
    assert recon["write_back_enabled"] is False
    assert recon["in_sync"] is False
    assert "someone_else" in recon["only_in_provider"]
