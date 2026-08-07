"""Communications provider conformance suite (§25) — Klaviyo reference adapter.

Runs the full offline conformance suite (generic certification checks + comms
domain checks) and asserts the reference adapter certifies with no failures and
an honest, credential-turnkey readiness state.
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


def test_klaviyo_passes_full_conformance_suite():
    from services.comms.conformance import certify_comms, COMMS_CONFORMANCE_CHECKS

    results = certify_comms()
    assert len(results) == len(COMMS_CONFORMANCE_CHECKS)
    failures = [r for r in results if not r.passed]
    assert not failures, [f"{r.name}: {r.detail}" for r in failures]
    # Every check applied (passed) or skipped honestly — none failed.
    assert all(r.passed for r in results)


def test_hubspot_passes_full_conformance_suite():
    from services.comms.conformance import certify_comms, COMMS_CONFORMANCE_CHECKS

    results = certify_comms(connector_type="hubspot")
    assert len(results) == len(COMMS_CONFORMANCE_CHECKS)
    failures = [r for r in results if not r.passed]
    assert not failures, [f"{r.name}: {r.detail}" for r in failures]
    assert all(r.passed for r in results)


def test_iterable_passes_full_conformance_suite():
    """Iterable (pull-capable, native HMAC webhook) certifies with no failures."""
    from services.comms.conformance import certify_comms, COMMS_CONFORMANCE_CHECKS

    results = certify_comms(connector_type="iterable")
    assert len(results) == len(COMMS_CONFORMANCE_CHECKS)
    failures = [r for r in results if not r.passed]
    assert not failures, [f"{r.name}: {r.detail}" for r in failures]
    assert all(r.passed for r in results)
    # Iterable declares pull + backfill + a native query-param HMAC scheme.
    from services.comms.conformance import comms_certification_descriptor
    d = comms_certification_descriptor("iterable")
    assert d.pagination_model == "cursor"
    assert d.expected_webhook_headers == ["signature", "ts"]


def test_braze_passes_full_conformance_suite():
    """The pull-first Braze adapter certifies with no failures (ADR-C11 follow-up)."""
    from services.comms.conformance import certify_comms, COMMS_CONFORMANCE_CHECKS

    results = certify_comms(connector_type="braze")
    assert len(results) == len(COMMS_CONFORMANCE_CHECKS)
    failures = [r for r in results if not r.passed]
    assert not failures, [f"{r.name}: {r.detail}" for r in failures]
    # Every check applied (passed) or skipped honestly — none failed.
    assert all(r.passed for r in results)


def test_comms_domain_checks_all_apply():
    """The comms-domain checks are not silently skipping — each asserts a real
    §25 property (manifest, credential absence, normalization, identity,
    webhook, suppression, reconciliation, backfill, account discovery)."""
    from services.comms.conformance import certify_comms

    results = {r.name: r for r in certify_comms()}
    # Explicit set of comms-domain check names that must be present and passed.
    expected = {
        "comms_manifest_completeness",
        "comms_credential_absence",
        "comms_provider_account_discovery",
        "comms_event_normalization",
        "comms_stable_event_identity",
        "comms_webhook_verification",
        "comms_suppression_mapping",
        "comms_reconciliation",
        "comms_backfill_boundary",
    }
    for name in expected:
        assert name in results, f"missing comms-domain check {name}"
        assert results[name].passed and not results[name].skipped, (
            f"{name}: {results[name].detail}"
        )


def test_certification_descriptor_is_honest():
    from services.comms.conformance import comms_certification_descriptor
    from shared.certification.readiness import CredentialReadiness

    d = comms_certification_descriptor("klaviyo")
    assert d.domain == "communications"
    assert d.first_release is True
    # Credential-gated, no live evidence → credential_waiting, never provider_live.
    assert d.implementation_state == CredentialReadiness.CREDENTIAL_WAITING
    assert "send" in d.unsupported_operations  # observe-only (ADR-C1)
    assert d.pagination_model == "cursor" and d.streaming_model == "webhook"


def test_registry_includes_all_communications_providers():
    """The certification registry enumerates every registered comms connector —
    no hardcoded list of one (ADR-C11 multi-provider)."""
    from shared.certification.registry import iter_first_release_descriptors

    descriptors = {(d.domain, d.provider) for d in iter_first_release_descriptors()}
    for provider in ("klaviyo", "sendgrid", "customerio", "mailchimp", "postmark",
                     "hubspot", "iterable", "braze"):
        assert ("communications", provider) in descriptors, (
            f"registry missing communications/{provider}"
        )


def test_every_comms_provider_passes_conformance_suite():
    """Each comms provider certifies with no failures: capabilities it declares
    are checked and pass; capabilities it does not declare skip honestly."""
    from services.comms.conformance import certify_comms

    for provider in ("klaviyo", "sendgrid", "customerio", "mailchimp", "postmark",
                     "hubspot", "iterable", "braze"):
        results = certify_comms(connector_type=provider)
        failures = [r for r in results if not r.passed]
        assert not failures, (
            f"{provider}: {[f'{r.name}: {r.detail}' for r in failures]}"
        )


def test_webhook_only_providers_do_not_claim_pull_operations():
    """The certification descriptor derives operations from the connector's
    declared manifest outputs + capability flags — a webhook-only provider never
    claims campaign/flow/message sync or pull/backfill/reconciliation (ADR-C11)."""
    from services.comms.conformance import comms_certification_descriptor

    pull_ops = {"campaign_sync", "flow_sync", "message_sync", "incremental_pull",
                "historical_backfill", "reconciliation", "reply_ingest"}
    for provider in ("sendgrid", "customerio", "mailchimp", "postmark"):
        ops = set(comms_certification_descriptor(provider).supported_operations)
        assert not (ops & pull_ops), f"{provider} claims pull operations {ops & pull_ops}"
        # Klaviyo is the reference that declares the full pull surface.
        assert pull_ops <= set(comms_certification_descriptor("klaviyo").supported_operations)
