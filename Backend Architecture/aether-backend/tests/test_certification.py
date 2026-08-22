"""Unit tests for the credentialless certification + readiness-truth framework
(``shared/certification``).

Covers:
- readiness: full ImplementationStatus mapping coverage, rank ordering,
  invariant enforcement, honest derive().
- checks: a fully-hooked fake adapter passes every applicable check; a
  descriptor-only adapter skips behavioral checks; secret redaction detects a
  leak; dishonest status is caught; run_certification records raises as failures.
- registry: the capability matrix is deterministic, the first-release scope is
  present, and states reflect source (interop scaffolds SCAFFOLDED, LayerZero
  CREDENTIAL_WAITING, etc.).
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from services.integrations.connectors.base import ImplementationStatus
from shared.certification.checks import (
    ALL_CHECKS,
    CertificationCheckResult,
    check_honest_status,
    check_secret_redaction,
    run_certification,
)
from shared.certification.descriptor import AdapterCertificationDescriptor
from shared.certification.readiness import (
    IMPLEMENTATION_STATUS_TO_READINESS,
    CredentialReadiness,
    ReadinessDimensions,
    readiness_rank,
    to_readiness,
)
from shared.certification.registry import (
    build_capability_matrix,
    iter_first_release_descriptors,
)


# ══════════════════════════════════════════════════════════════════════════
# Fake adapters
# ══════════════════════════════════════════════════════════════════════════

_SECRET_KEY_MARKERS = ("authorization", "api_key", "password", "token", "secret")


def _redact(value):
    if isinstance(value, dict):
        return {
            k: _redact(v)
            for k, v in value.items()
            if not any(m in str(k).lower() for m in _SECRET_KEY_MARKERS)
        }
    if isinstance(value, list):
        return [_redact(x) for x in value]
    return value


class GoodFakeAdapter:
    """An adapter that exposes every optional hook, honestly and correctly."""

    def certification_descriptor(self) -> AdapterCertificationDescriptor:
        return AdapterCertificationDescriptor(
            provider="fake",
            domain="test",
            adapter="GoodFakeAdapter",
            adapter_version="1.0.0",
            supported_operations=["read", "list"],
            unsupported_operations=["write"],
            required_credentials=["api_key"],
            secret_ref_names=["vault_fake"],
            expected_webhook_headers=["signature"],
            pagination_model="cursor",
            streaming_model="webhook",
            rate_limit_behavior="token_bucket",
            retry_policy="exponential_backoff",
            implementation_state=CredentialReadiness.CREDENTIAL_WAITING,
            fixture_schema_version="1",
            first_release=True,
        )

    def sanitize_payload(self, payload):
        return _redact(payload)

    def build_request(self, ctx):
        ctx = ctx or {}
        headers = {"Content-Type": "application/json"}
        cred = ctx.get("credential") or {}
        if cred:
            headers["Authorization"] = f"Bearer {cred.get('api_key') or cred.get('secret')}"
        tenant = ctx.get("tenant_id")
        if tenant:
            headers["X-Tenant-Id"] = tenant
        return {"url": "https://api.fake/v1/read", "method": "GET", "headers": headers}

    def normalize(self, payload):
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        return {"id": payload.get("id"), "type": payload.get("type")}

    def dedupe_key(self, event):
        return event.get("id")

    def sequence_of(self, event):
        return event.get("seq")

    def advance_cursor(self, cursor):
        return f"{cursor}_next"

    def health(self, context):
        if not context.get("configured"):
            return {"state": "not_configured", "healthy": False}
        return {"state": "ok", "healthy": True}


class DescriptorOnlyAdapter:
    """Exposes only a descriptor — behavioral checks must skip, not fail."""

    def certification_descriptor(self) -> AdapterCertificationDescriptor:
        return AdapterCertificationDescriptor(
            provider="thin",
            domain="test",
            adapter="DescriptorOnlyAdapter",
            adapter_version="0.1.0",
            supported_operations=["read"],
            implementation_state=CredentialReadiness.SCAFFOLDED,
        )


class LeakySanitizerAdapter:
    """A dishonest sanitizer that does not redact — must be caught."""

    def certification_descriptor(self) -> AdapterCertificationDescriptor:
        return AdapterCertificationDescriptor(
            provider="leaky",
            domain="test",
            adapter="LeakySanitizerAdapter",
            implementation_state=CredentialReadiness.CREDENTIAL_WAITING,
        )

    def sanitize_payload(self, payload):
        return payload  # returns everything unchanged — a leak


# ══════════════════════════════════════════════════════════════════════════
# readiness.py
# ══════════════════════════════════════════════════════════════════════════


def test_mapping_covers_every_implementation_status():
    for status in ImplementationStatus:
        assert status in IMPLEMENTATION_STATUS_TO_READINESS, f"unmapped: {status}"
        assert isinstance(IMPLEMENTATION_STATUS_TO_READINESS[status], CredentialReadiness)


def test_mapping_exact_values():
    assert to_readiness(ImplementationStatus.SCAFFOLDED) == CredentialReadiness.SCAFFOLDED
    assert to_readiness(ImplementationStatus.PRODUCTION_SHAPED) == CredentialReadiness.CREDENTIAL_WAITING
    assert to_readiness(ImplementationStatus.CREDENTIAL_GATED) == CredentialReadiness.CREDENTIAL_WAITING
    assert to_readiness(ImplementationStatus.PROVIDER_LIVE) == CredentialReadiness.PARTNER_LIVE
    assert to_readiness(ImplementationStatus.WAREHOUSE_DATASHARE_READY) == CredentialReadiness.CREDENTIAL_WAITING
    assert to_readiness(ImplementationStatus.STAGING_VALIDATION_REQUIRED) == CredentialReadiness.CREDENTIAL_WAITING
    assert to_readiness(ImplementationStatus.DISABLED_COMPLIANCE_REVIEW) == CredentialReadiness.DISABLED
    assert to_readiness(ImplementationStatus.DEPRECATED) == CredentialReadiness.DISABLED


def test_to_readiness_accepts_string_value_and_rejects_unknown():
    with pytest.raises(ValueError):
        to_readiness("mocked_local")
    with pytest.raises(ValueError):
        to_readiness("not_a_status")


def test_readiness_rank_progression():
    order = [
        CredentialReadiness.SCAFFOLDED,
        CredentialReadiness.CREDENTIAL_WAITING,
        CredentialReadiness.REPLAY_VALIDATED,
        CredentialReadiness.SANDBOX_VALIDATED,
        CredentialReadiness.PARTNER_LIVE,
    ]
    ranks = [readiness_rank(r) for r in order]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)


def test_degraded_disabled_rank_below_progression():
    threshold = readiness_rank(CredentialReadiness.CREDENTIAL_WAITING)
    assert readiness_rank(CredentialReadiness.DEGRADED) < threshold
    assert readiness_rank(CredentialReadiness.DISABLED) < threshold
    # "at least CREDENTIAL_WAITING" must exclude off-ramp states and SCAFFOLDED
    assert readiness_rank(CredentialReadiness.SCAFFOLDED) < threshold
    assert readiness_rank(CredentialReadiness.PARTNER_LIVE) >= threshold


def test_dimensions_defaults():
    d = ReadinessDimensions()
    assert d.credential_required is True
    assert d.production_ready is False
    # every other boolean defaults False
    for field in (
        "code_complete", "infra_defined", "credential_supplied", "replay_validated",
        "sandbox_validated", "live_validated", "security_reviewed", "externally_audited",
        "requires_external_audit", "pilot_ready",
    ):
        assert getattr(d, field) is False


def test_invariant_production_ready_requires_live_and_security():
    with pytest.raises(ValueError):
        ReadinessDimensions(production_ready=True, live_validated=True, credential_supplied=True)
    with pytest.raises(ValueError):
        ReadinessDimensions(production_ready=True, security_reviewed=True)
    # honest: both present (and credential supplied for live) is accepted
    ok = ReadinessDimensions(
        production_ready=True,
        live_validated=True,
        credential_supplied=True,
        security_reviewed=True,
    )
    assert ok.production_ready is True


def test_invariant_external_audit_gate():
    with pytest.raises(ValueError):
        ReadinessDimensions(
            production_ready=True,
            live_validated=True,
            credential_supplied=True,
            security_reviewed=True,
            requires_external_audit=True,
            externally_audited=False,
        )
    ok = ReadinessDimensions(
        production_ready=True,
        live_validated=True,
        credential_supplied=True,
        security_reviewed=True,
        requires_external_audit=True,
        externally_audited=True,
    )
    assert ok.externally_audited is True


def test_invariant_sandbox_implies_replay():
    with pytest.raises(ValueError):
        ReadinessDimensions(sandbox_validated=True, replay_validated=False)


def test_invariant_live_implies_credential():
    with pytest.raises(ValueError):
        ReadinessDimensions(live_validated=True, credential_supplied=False)


def test_invariant_pilot_ready_prerequisites():
    with pytest.raises(ValueError):
        ReadinessDimensions(pilot_ready=True, code_complete=True, infra_defined=True)
    ok = ReadinessDimensions(
        pilot_ready=True, code_complete=True, infra_defined=True, replay_validated=True
    )
    assert ok.pilot_ready is True


def test_derive_is_honest():
    assert ReadinessDimensions.derive().state == CredentialReadiness.SCAFFOLDED
    assert (
        ReadinessDimensions.derive(code_complete=True, credential_required=False).state
        == CredentialReadiness.SCAFFOLDED
    )
    assert (
        ReadinessDimensions.derive(code_complete=True, infra_defined=True).state
        == CredentialReadiness.CREDENTIAL_WAITING
    )
    assert (
        ReadinessDimensions.derive(replay_validated=True).state
        == CredentialReadiness.REPLAY_VALIDATED
    )
    assert (
        ReadinessDimensions.derive(
            replay_validated=True,
            sandbox_validated=True,
            credential_supplied=True,
            connection_validated=True,
        ).state
        == CredentialReadiness.SANDBOX_VALIDATED
    )
    # a credential-free capability may reach sandbox without a connection test
    assert (
        ReadinessDimensions.derive(
            replay_validated=True, sandbox_validated=True, credential_required=False
        ).state
        == CredentialReadiness.SANDBOX_VALIDATED
    )
    assert (
        ReadinessDimensions.derive(
            code_complete=True, infra_defined=True, credential_supplied=True
        ).state
        == CredentialReadiness.CREDENTIAL_SUPPLIED
    )
    assert (
        ReadinessDimensions.derive(
            code_complete=True,
            infra_defined=True,
            credential_supplied=True,
            connection_validated=True,
        ).state
        == CredentialReadiness.CONNECTION_VALIDATED
    )
    live = ReadinessDimensions.derive(live_validated=True, credential_supplied=True)
    assert live.state == CredentialReadiness.PARTNER_LIVE
    # derive never turns production_ready on from structure
    assert live.production_ready is False


def test_new_lifecycle_invariants_fail_closed():
    # connection_validated without a supplied credential is dishonest
    with pytest.raises(ValueError):
        ReadinessDimensions(connection_validated=True, credential_supplied=False)
    # credential-gated sandbox validation without a connection test is dishonest
    with pytest.raises(ValueError):
        ReadinessDimensions(
            replay_validated=True,
            sandbox_validated=True,
            credential_supplied=True,
            connection_validated=False,
        )


def test_offramp_states_rank_below_progression():
    threshold = readiness_rank(CredentialReadiness.CREDENTIAL_WAITING)
    for off in (
        CredentialReadiness.DEGRADED,
        CredentialReadiness.SUSPENDED,
        CredentialReadiness.REVOKED,
        CredentialReadiness.DISABLED,
    ):
        assert readiness_rank(off) < threshold
    # severity order among off-ramps: disabled < revoked < suspended < degraded
    assert (
        readiness_rank(CredentialReadiness.DISABLED)
        < readiness_rank(CredentialReadiness.REVOKED)
        < readiness_rank(CredentialReadiness.SUSPENDED)
        < readiness_rank(CredentialReadiness.DEGRADED)
    )


def test_full_progression_rank_order():
    order = [
        CredentialReadiness.SCAFFOLDED,
        CredentialReadiness.CREDENTIAL_WAITING,
        CredentialReadiness.REPLAY_VALIDATED,
        CredentialReadiness.CREDENTIAL_SUPPLIED,
        CredentialReadiness.CONNECTION_VALIDATED,
        CredentialReadiness.SANDBOX_VALIDATED,
        CredentialReadiness.PARTNER_LIVE,
    ]
    ranks = [readiness_rank(s) for s in order]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)


def test_derive_enforces_invariants():
    with pytest.raises(ValueError):
        ReadinessDimensions.derive(live_validated=True, credential_supplied=False)


# ══════════════════════════════════════════════════════════════════════════
# checks.py
# ══════════════════════════════════════════════════════════════════════════


def test_good_adapter_passes_every_applicable_check():
    ctx = {"timeout_seconds": 30}
    results = run_certification(GoodFakeAdapter(), ctx)
    assert len(results) == len(ALL_CHECKS)
    failed = [r for r in results if not r.passed]
    skipped = [r for r in results if r.skipped]
    assert failed == [], f"unexpected failures: {[(r.name, r.detail) for r in failed]}"
    # with timeout supplied and all hooks present, nothing should skip
    assert skipped == [], f"unexpected skips: {[r.name for r in skipped]}"


def test_descriptor_only_adapter_skips_behavioral_checks():
    results = {r.name: r for r in run_certification(DescriptorOnlyAdapter())}
    assert [r for r in results.values() if not r.passed] == []
    # descriptor-level checks still run
    assert results["descriptor_completeness"].skipped is False
    assert results["honest_status"].skipped is False
    # behavioral checks skip (no hooks)
    for name in (
        "secret_redaction", "request_construction", "auth_injection",
        "duplicate_handling", "out_of_order_handling", "schema_drift",
        "malformed_input", "idempotent_replay", "health_transitions",
        "tenant_isolation",
    ):
        assert results[name].skipped is True, f"{name} should have skipped"


def test_secret_redaction_detects_leak():
    good = check_secret_redaction(GoodFakeAdapter(), {})
    assert good.passed and not good.skipped
    leak = check_secret_redaction(LeakySanitizerAdapter(), {})
    assert leak.passed is False, "unredacted secret payload must fail"
    assert "secret material survived" in leak.detail


def test_secret_redaction_skips_without_sanitizer():
    result = check_secret_redaction(DescriptorOnlyAdapter(), {})
    assert result.skipped is True


def test_honest_status_rejects_unproven_partner_live():
    descriptor = AdapterCertificationDescriptor(
        provider="bragger",
        domain="test",
        adapter="Bragger",
        implementation_state=CredentialReadiness.PARTNER_LIVE,
    )
    fail = check_honest_status(descriptor, {})
    assert fail.passed is False and "no live evidence" in fail.detail
    # with live evidence supplied, the same claim is accepted
    ok = check_honest_status(descriptor, {"live_evidence": True})
    assert ok.passed is True


def test_run_certification_records_raising_check_as_failure():
    def exploding_check(adapter, ctx):
        raise RuntimeError("boom")

    results = run_certification(GoodFakeAdapter(), {}, checks=[exploding_check])
    assert len(results) == 1
    assert results[0].passed is False
    assert "boom" in results[0].detail


def test_run_certification_accepts_bare_descriptor():
    descriptor = AdapterCertificationDescriptor(
        provider="bare",
        domain="test",
        adapter="Bare",
        implementation_state=CredentialReadiness.CREDENTIAL_WAITING,
    )
    results = run_certification(descriptor)
    assert any(r.name == "descriptor_completeness" and r.passed for r in results)


def test_check_result_model_shape():
    r = CertificationCheckResult(name="x", passed=True)
    assert r.skipped is False and r.detail == ""


# ══════════════════════════════════════════════════════════════════════════
# registry.py
# ══════════════════════════════════════════════════════════════════════════


def test_matrix_is_deterministic_across_two_calls():
    a = build_capability_matrix()
    b = build_capability_matrix()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_matrix_is_json_serializable_and_sorted():
    matrix = build_capability_matrix()
    dumped = json.dumps(matrix)  # must not raise
    assert dumped
    keys = list(matrix["providers"].keys())
    assert keys == sorted(keys)


def test_first_release_scope_present():
    matrix = build_capability_matrix()
    keys = set(matrix["providers"].keys())
    expected = {
        # payments
        "payments:privy", "payments:stripe_onramp", "payments:coinbase",
        "payments:moonpay", "payments:bridge",
        # interop
        "interop:layerzero", "interop:wormhole", "interop:axelar",
        "interop:chainlink_ccip", "interop:hyperlane", "interop:ibc",
        "interop:debridge",
        # derivatives
        "derivatives:hyperliquid", "derivatives:dydx", "derivatives:gmx",
        "derivatives:drift",
        # stablecoin chain
        "stablecoin_chain:evm", "stablecoin_chain:svm",
    }
    assert expected <= keys
    assert matrix["summary"]["total"] == len(keys)


def test_states_reflect_source_reality():
    providers = build_capability_matrix()["providers"]
    # interop: LayerZero + the six former scaffolds are all real, credential-gated
    # decoders now (source-resolved from INTEROP_PROVIDERS).
    for pid in ("layerzero", "wormhole", "axelar", "chainlink_ccip", "hyperlane", "ibc", "debridge"):
        assert providers[f"interop:{pid}"]["state"] == CredentialReadiness.CREDENTIAL_WAITING.value
    # derivatives: Hyperliquid connector + the real dYdX/GMX/Drift venue adapters.
    for pid in ("hyperliquid", "dydx", "gmx", "drift"):
        assert providers[f"derivatives:{pid}"]["state"] == CredentialReadiness.CREDENTIAL_WAITING.value


def test_all_descriptors_are_first_release():
    descriptors = iter_first_release_descriptors()
    assert descriptors, "expected a non-empty first-release scope"
    assert all(d.first_release for d in descriptors)
    # sorted deterministically by (domain, provider)
    keys = [(d.domain, d.provider) for d in descriptors]
    assert keys == sorted(keys)


def test_summary_counts_are_consistent():
    matrix = build_capability_matrix()
    summary = matrix["summary"]
    assert sum(summary["by_state"].values()) == summary["total"]
    assert sum(summary["by_domain"].values()) == summary["total"]
    assert summary["first_release"] == summary["total"]


# ══════════════════════════════════════════════════════════════════════════
# Registry — import-failure honesty
# ══════════════════════════════════════════════════════════════════════════


def test_healthy_build_reports_no_import_errors():
    """In this repo every first-release adapter must resolve; a non-empty map
    would mean a SCAFFOLDED entry is a silent import failure, not an honest
    absence."""
    from shared.certification import registry as reg

    reg.iter_first_release_descriptors()
    assert reg.import_errors() == {}
    assert build_capability_matrix()["summary"]["import_errors"] == {}


def test_import_failure_is_recorded_not_silent():
    """A broken module import degrades to None (state resolves SCAFFOLDED) but
    MUST leave a distinguishable record in import_errors()."""
    from shared.certification import registry as reg

    assert reg._import("services.no_such_module_xyz", "Missing") is None
    errors = reg.import_errors()
    assert "services.no_such_module_xyz:Missing" in errors
    assert "ModuleNotFoundError" in errors["services.no_such_module_xyz:Missing"]
    # cleanup so later matrix builds in this process stay honest-empty
    reg._IMPORT_ERRORS.pop("services.no_such_module_xyz:Missing", None)


def test_missing_attribute_is_recorded_and_recovery_clears_it():
    from shared.certification import registry as reg

    assert reg._import("shared.certification.readiness", "NoSuchAttr") is None
    assert (
        reg.import_errors()["shared.certification.readiness:NoSuchAttr"]
        == "AttributeError: attribute missing"
    )
    # a successful resolution never leaves a record behind for its own key
    assert reg._import("shared.certification.readiness", "CredentialReadiness") is not None
    assert "shared.certification.readiness:CredentialReadiness" not in reg.import_errors()
    # cleanup so later matrix builds in this process stay honest-empty
    reg._IMPORT_ERRORS.pop("shared.certification.readiness:NoSuchAttr", None)
