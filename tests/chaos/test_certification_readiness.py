"""Certification-plane honesty invariants (the scorecard's load-bearing claim).

The final scorecard (scripts/production_status.py) rests on one honesty rule:
credential-waiting is NOT production-ready, and structure never confers
``production_ready``. These tests pin that rule so a future edit cannot quietly
promote a provider without live evidence.

Drives the REAL certification plane (``shared.certification``). No live calls.
"""

from __future__ import annotations

import pytest

from shared.certification.readiness import (
    CredentialReadiness,
    ReadinessDimensions,
    readiness_rank,
)
from shared.certification.registry import build_capability_matrix


# ── all 23 first-release providers are uniformly credential_waiting ───────────
def test_all_first_release_providers_are_credential_waiting():
    matrix = build_capability_matrix()
    summary = matrix["summary"]
    assert summary["total"] == 23
    assert summary["first_release"] == 23
    assert summary["by_state"] == {"credential_waiting": 23}
    # none are production/partner-live, none are scaffolded (forbidden for release)
    states = {p["state"] for p in matrix["providers"].values()}
    assert states == {"credential_waiting"}


def test_provider_domains_match_the_shipped_scope():
    matrix = build_capability_matrix()
    # communications: the five-provider cohort (ADR-C11) — Klaviyo is the
    # certified reference pull adapter, the other four are webhook-only.
    assert matrix["summary"]["by_domain"] == {
        "communications": 5, "derivatives": 4, "interop": 7, "payments": 5,
        "stablecoin_chain": 2,
    }


# ── credential_waiting is strictly below live states ──────────────────────────
def test_credential_waiting_ranks_below_replay_sandbox_and_partner_live():
    cw = readiness_rank(CredentialReadiness.CREDENTIAL_WAITING)
    assert cw < readiness_rank(CredentialReadiness.REPLAY_VALIDATED)
    assert cw < readiness_rank(CredentialReadiness.SANDBOX_VALIDATED)
    assert cw < readiness_rank(CredentialReadiness.PARTNER_LIVE)
    # off-ramp states rank below credential_waiting so ">= CREDENTIAL_WAITING"
    # never admits a degraded/disabled provider
    assert readiness_rank(CredentialReadiness.DEGRADED) < cw
    assert readiness_rank(CredentialReadiness.DISABLED) < cw


# ── production_ready is never inferred from structure ─────────────────────────
def test_production_ready_requires_live_validation_and_security_review():
    with pytest.raises(ValueError):
        ReadinessDimensions(
            code_complete=True, infra_defined=True, production_ready=True
        )  # no live_validated / security_reviewed


def test_production_ready_requires_external_audit_when_flagged():
    with pytest.raises(ValueError):
        ReadinessDimensions(
            code_complete=True, infra_defined=True,
            credential_supplied=True, live_validated=True, security_reviewed=True,
            requires_external_audit=True, production_ready=True,  # not externally_audited
        )


def test_derive_from_credential_evidence_yields_credential_waiting_not_more():
    dims = ReadinessDimensions.derive(
        code_complete=True, infra_defined=True, credential_required=True
    )
    assert dims.state == CredentialReadiness.CREDENTIAL_WAITING
    assert dims.production_ready is False


def test_pilot_ready_requires_replay_evidence():
    with pytest.raises(ValueError):
        ReadinessDimensions(code_complete=True, infra_defined=True, pilot_ready=True)
    # a legitimately pilot-ready record needs replay evidence
    ok = ReadinessDimensions(
        code_complete=True, infra_defined=True, replay_validated=True, pilot_ready=True
    )
    assert ok.pilot_ready is True
