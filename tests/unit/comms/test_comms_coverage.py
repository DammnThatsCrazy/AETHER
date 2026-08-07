"""Cross-provider comms coverage scoring (commit-12) — honest, evidence-grounded.

The coverage report is a per-provider view of what Aether has actually observed
(identity-bridge mappings, active suppressions) next to each provider's declared
capabilities. Zeros are honest zeros; a provider that has never observed
anything reports zero — never "complete".
"""

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


@pytest.fixture
def comms_coverage():
    from services.comms import coverage
    return coverage


@pytest.mark.asyncio
async def test_comms_providers_includes_full_cohort(comms_coverage):
    """All comms providers are registered and comms-classified."""
    providers = comms_coverage.comms_providers()
    assert {"klaviyo", "sendgrid", "customerio", "mailchimp", "postmark",
            "hubspot"} <= set(providers)


@pytest.mark.asyncio
async def test_provider_coverage_reports_grounded_observations(comms_coverage):
    """Identity + suppression counts come from the store, not from assertions."""
    from services.comms.identity_bridge import ProviderIdentityBridge
    from services.comms.suppression_authority import SuppressionAuthorityService

    bridge = ProviderIdentityBridge()
    # provisional (no canonical entity in local)
    await bridge.record_observation(
        tenant_id="t1", provider="klaviyo", provider_account_id="acct-1",
        provider_profile_id="prof-1", raw_email="a@example.com",
    )
    # resolved (canonical entity supplied explicitly)
    await bridge.record_observation(
        tenant_id="t1", provider="klaviyo", provider_account_id="acct-1",
        provider_profile_id="prof-2", raw_email="b@example.com",
        canonical_entity_id="ent-1",
    )
    # a different provider must not leak into klaviyo's counts
    await bridge.record_observation(
        tenant_id="t1", provider="sendgrid", provider_account_id="acct-9",
        provider_profile_id="prof-9", raw_email="c@example.com",
    )

    sup = SuppressionAuthorityService()
    await sup.record("t1", reason="spam_complaint", scope="recipient",
                     provider="klaviyo", recipient_alias_id="alias-1")
    await sup.record("t1", reason="manual", scope="recipient",
                     provider="klaviyo", recipient_alias_id="alias-2")

    entry = await comms_coverage.provider_coverage("t1", "klaviyo")
    assert entry is not None
    assert entry["identities_observed"] == 2
    assert entry["identities_resolved"] == 1
    assert entry["identities_provisional"] == 1
    assert entry["identity_resolution_rate"] == pytest.approx(0.5)
    assert entry["active_suppressions"] == 2
    # declared capabilities surface honestly (webhook true, pull/reconcile per connector)
    assert entry["capabilities"]["supports_webhook"] is True
    assert entry["capabilities"]["supports_reconciliation"] is True  # klaviyo declares it
    assert entry["capabilities"]["required_credentials"] == ()


@pytest.mark.asyncio
async def test_non_comms_provider_is_none(comms_coverage):
    assert await comms_coverage.provider_coverage("t1", "shopify") is None


@pytest.mark.asyncio
async def test_report_covers_every_registered_provider(comms_coverage):
    report = await comms_coverage.comms_coverage_report("t1")
    providers = {r["provider"] for r in report}
    assert {"klaviyo", "sendgrid", "customerio", "mailchimp", "postmark",
            "hubspot"} <= providers
    # every entry carries capabilities + honest zero coverage
    for entry in report:
        assert "capabilities" in entry
        assert entry["identities_observed"] >= 0
        assert entry["active_suppressions"] >= 0


@pytest.mark.asyncio
async def test_report_provider_scope(comms_coverage):
    report = await comms_coverage.comms_coverage_report("t1", provider="sendgrid")
    assert [r["provider"] for r in report] == ["sendgrid"]
