"""Certification contracts: readiness-token parity with CredentialReadiness."""

from __future__ import annotations

import pytest

from shared.certification.readiness import CredentialReadiness
from shared.integration_contracts.certification import (
    CertificationCheck,
    CertificationReport,
    ProviderReadinessLevel,
)
from shared.integration_contracts.manifest import ManifestReadiness


def test_readiness_level_mirrors_credential_readiness_tokens() -> None:
    # Every ProviderReadinessLevel token string equals the mission-canonical
    # CredentialReadiness token string — a lossless, one-to-one value mapping.
    assert {m.name: m.value for m in ProviderReadinessLevel} == {
        m.name: m.value for m in CredentialReadiness
    }
    assert set(ProviderReadinessLevel.__members__) == set(CredentialReadiness.__members__)


def test_readiness_level_enum_values() -> None:
    assert ProviderReadinessLevel.REPLAY_VALIDATED.value == "replay_validated"
    assert ProviderReadinessLevel.CREDENTIAL_WAITING.value == "credential_waiting"
    assert ProviderReadinessLevel.SANDBOX_VALIDATED.value == "sandbox_validated"
    assert ProviderReadinessLevel.PARTNER_LIVE.value == "partner_live"
    assert ProviderReadinessLevel.DEGRADED.value == "degraded"
    assert ProviderReadinessLevel.DISABLED.value == "disabled"
    assert ProviderReadinessLevel.SCAFFOLDED.value == "scaffolded"


def test_certification_check_defaults() -> None:
    c = CertificationCheck(name="manifest-honest", passed=True)
    assert c.detail == ""


def test_certification_check_forbids_unknown_fields() -> None:
    with pytest.raises(Exception):
        CertificationCheck(name="x", passed=True, unexpected_field=True)  # type: ignore[call-arg]


def test_certification_report_defaults() -> None:
    r = CertificationReport(
        generated_at="2026-01-01T00:00:00+00:00",
        identity="shopify.admin.orders_read",
        readiness=ManifestReadiness(state=CredentialReadiness.SANDBOX_VALIDATED, level=4),
        checks=[CertificationCheck(name="manifest-honest", passed=True)],
        passed=True,
    )
    assert r.schema_version == "1"
    assert r.plugin_version == ""
    assert r.environment == "local"


def test_certification_report_requires_identity_and_checks() -> None:
    with pytest.raises(Exception):
        CertificationReport(  # type: ignore[call-arg]
            generated_at="2026-01-01T00:00:00+00:00",
            readiness=ManifestReadiness(state=CredentialReadiness.SANDBOX_VALIDATED, level=4),
            passed=True,
        )


def test_certification_report_forbids_unknown_fields() -> None:
    with pytest.raises(Exception):
        CertificationReport(  # type: ignore[call-arg]
            generated_at="2026-01-01T00:00:00+00:00",
            identity="shopify.admin.orders_read",
            readiness=ManifestReadiness(state=CredentialReadiness.SANDBOX_VALIDATED, level=4),
            checks=[],
            passed=True,
            unexpected_field=True,
        )


def test_certification_report_accepts_explicit_plugin_version_and_environment() -> None:
    r = CertificationReport(
        generated_at="2026-01-01T00:00:00+00:00",
        identity="shopify.admin.orders_read",
        plugin_version="1.2.3",
        readiness=ManifestReadiness(state=CredentialReadiness.PARTNER_LIVE, level=5),
        environment="staging",
        checks=[],
        passed=True,
    )
    assert r.plugin_version == "1.2.3"
    assert r.environment == "staging"
