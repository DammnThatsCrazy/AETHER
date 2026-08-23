"""Tests for model-runtime observability runbooks + incident classification.

Covers the runbook data model (frozen, severity literal), the default catalog
coverage of all six ADR-008 D8 incident types, deterministic
``IncidentClassifier`` precedence, the ``recommend`` convenience, the "no
credential-shaped literals in steps" security invariant, and clean package
imports (including sibling-module names owned by Agents A-E).
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

# The package imports cleanly even while sibling modules (readiness.py, etc.)
# land concurrently; runbook symbols are always real.
from services.model_runtime.observability import (
    CanaryMetrics,
    CanaryPolicy,
    CanarySelector,
    CanaryTracker,
    CircuitBreaker,
    CircuitRegistry,
    CircuitState,
    FailClosed,
    IncidentClassifier,
    MetricNames,
    NullMetricsRecorder,
    ProviderHealth,
    ProviderHealthCheck,
    ReadinessState,
    Runbook,
    RunbookCatalog,
    RuntimeHealth,
    RuntimeHealthProbe,
    RuntimeMetricsRecorder,
    RuntimeReadiness,
    recommend,
)

INCIDENT_TYPES = (
    "provider_outage",
    "circuit_open",
    "credential_rotation",
    "verification_block",
    "budget_exceeded",
    "misconfigured_failclosed",
)

# Credential-shaped literals that must never appear in runbook steps. Bare nouns
# like "secret backend" or "credentials" (generic ops instructions) are allowed;
# only secret VALUES / key names are forbidden.
_SECRET_PATTERN = re.compile(
    r"sk-[A-Za-z0-9_-]{8,}"
    r"|AKIA[0-9A-Z]{12,}"
    r"|Bearer\s+[A-Za-z0-9._~-]{8,}"
    r"|-----BEGIN[ A-Z]*PRIVATE KEY-----"
    r"|\bpassword\b"
    r"|\bapi[_-]?key\b"
    r"|\bclient[_-]?secret\b"
    r"|(?:Authorization|X-Api-Key)\s*:"
)


def test_default_catalog_covers_all_incident_types():
    catalog = RunbookCatalog()
    assert len(catalog.all()) == len(INCIDENT_TYPES)
    for incident_type in INCIDENT_TYPES:
        runbook = catalog.get(incident_type)
        assert runbook.apply_to == (incident_type,)
        assert runbook.severity in ("info", "warning", "critical")
        assert runbook.steps
        assert runbook.id == incident_type


def test_runbook_is_frozen():
    runbook = Runbook(
        id="x",
        title="t",
        summary="s",
        severity="warning",
        steps=("a",),
        apply_to=("provider_outage",),
    )
    with pytest.raises(ValidationError):
        runbook.title = "changed"


def test_runbook_severity_literal_enforced():
    with pytest.raises(ValidationError):
        Runbook(
            id="x",
            title="t",
            summary="s",
            severity="severe",
            steps=("a",),
            apply_to=("provider_outage",),
        )


def test_custom_catalog():
    custom = RunbookCatalog(
        [
            Runbook(
                id="custom",
                title="c",
                summary="s",
                severity="info",
                steps=("do the thing",),
                apply_to=("custom_incident",),
            )
        ]
    )
    assert custom.get("custom_incident").id == "custom"
    assert custom.all() == (custom.get("custom_incident"),)


def test_get_unknown_type_raises_keyerror():
    with pytest.raises(KeyError):
        RunbookCatalog().get("nonexistent")


def test_classify_misconfigured_beats_everything():
    assert (
        IncidentClassifier.classify(
            config_ok=False,
            circuit_open=True,
            provider_errors=10,
            credential_missing=True,
            budget_exceeded=True,
            verification_failures=10,
        )
        == "misconfigured_failclosed"
    )


def test_classify_circuit_beats_provider_and_below():
    assert (
        IncidentClassifier.classify(
            config_ok=True,
            circuit_open=True,
            provider_errors=10,
            credential_missing=True,
            budget_exceeded=True,
            verification_failures=10,
        )
        == "circuit_open"
    )


def test_classify_provider_beats_credential_budget_verification():
    assert (
        IncidentClassifier.classify(
            config_ok=True,
            circuit_open=False,
            provider_errors=5,
            credential_missing=True,
            budget_exceeded=True,
            verification_failures=10,
        )
        == "provider_outage"
    )


def test_classify_provider_outage_threshold():
    # below threshold (4) is not provider_outage; the next signal decides.
    assert (
        IncidentClassifier.classify(
            config_ok=True,
            circuit_open=False,
            provider_errors=4,
            credential_missing=False,
            budget_exceeded=False,
            verification_failures=0,
        )
        == "ok"
    )
    assert (
        IncidentClassifier.classify(
            config_ok=True,
            circuit_open=False,
            provider_errors=5,
            credential_missing=False,
            budget_exceeded=False,
            verification_failures=0,
        )
        == "provider_outage"
    )


def test_classify_credential_beats_budget_verification():
    assert (
        IncidentClassifier.classify(
            config_ok=True,
            circuit_open=False,
            provider_errors=0,
            credential_missing=True,
            budget_exceeded=True,
            verification_failures=10,
        )
        == "credential_rotation"
    )


def test_classify_budget_beats_verification():
    assert (
        IncidentClassifier.classify(
            config_ok=True,
            circuit_open=False,
            provider_errors=0,
            credential_missing=False,
            budget_exceeded=True,
            verification_failures=10,
        )
        == "budget_exceeded"
    )


def test_classify_verification_block_threshold():
    assert (
        IncidentClassifier.classify(
            config_ok=True,
            circuit_open=False,
            provider_errors=0,
            credential_missing=False,
            budget_exceeded=False,
            verification_failures=3,
        )
        == "verification_block"
    )
    assert (
        IncidentClassifier.classify(
            config_ok=True,
            circuit_open=False,
            provider_errors=0,
            credential_missing=False,
            budget_exceeded=False,
            verification_failures=2,
        )
        == "ok"
    )


def test_classify_ok_when_all_clear():
    assert (
        IncidentClassifier.classify(
            config_ok=True,
            circuit_open=False,
            provider_errors=0,
            credential_missing=False,
            budget_exceeded=False,
            verification_failures=0,
        )
        == "ok"
    )


def test_recommend_returns_runbook():
    runbook = recommend("credential_rotation")
    assert isinstance(runbook, Runbook)
    assert runbook.id == "credential_rotation"
    # explicit catalog wins over the default.
    custom = RunbookCatalog(
        [
            Runbook(
                id="custom",
                title="c",
                summary="s",
                severity="info",
                steps=("do the thing",),
                apply_to=("custom_incident",),
            )
        ]
    )
    assert recommend("custom_incident", custom).id == "custom"


def test_runbook_steps_contain_no_secret_patterns():
    for runbook in RunbookCatalog().all():
        for field in (runbook.title, runbook.summary):
            assert not _SECRET_PATTERN.search(field), f"secret-like: {field!r}"
        for step in runbook.steps:
            assert not _SECRET_PATTERN.search(step), f"secret-like step: {step!r}"


def test_package_imports_cleanly_with_sibling_symbols():
    # Cross-team contract import must not raise, even while siblings land
    # concurrently. Landed siblings resolve to real classes; unlanded ones are
    # bound to None by the guarded re-exports in __init__.py.
    for symbol in (
        MetricNames,
        RuntimeMetricsRecorder,
        NullMetricsRecorder,
        ProviderHealth,
        RuntimeHealth,
        ProviderHealthCheck,
        RuntimeHealthProbe,
        ReadinessState,
        RuntimeReadiness,
        FailClosed,
        CircuitState,
        CircuitBreaker,
        CircuitRegistry,
        CanaryPolicy,
        CanarySelector,
        CanaryTracker,
        CanaryMetrics,
    ):
        assert symbol is None or isinstance(symbol, type), symbol


def test_runbook_symbols_are_real():
    assert isinstance(Runbook, type)
    assert isinstance(RunbookCatalog, type)
    assert isinstance(IncidentClassifier, type)
    assert callable(recommend)


def test_all_contains_full_public_api():
    import services.model_runtime.observability as obs

    for name in (
        "MetricNames",
        "RuntimeMetricsRecorder",
        "NullMetricsRecorder",
        "ProviderHealth",
        "RuntimeHealth",
        "ProviderHealthCheck",
        "RuntimeHealthProbe",
        "ReadinessState",
        "RuntimeReadiness",
        "FailClosed",
        "CircuitState",
        "CircuitBreaker",
        "CircuitRegistry",
        "CanaryPolicy",
        "CanarySelector",
        "CanaryTracker",
        "CanaryMetrics",
        "Runbook",
        "RunbookCatalog",
        "IncidentClassifier",
        "recommend",
    ):
        assert name in obs.__all__
        assert getattr(obs, name) is not None or name in (
            # unlanded siblings bind to None until their module lands.
            "ReadinessState",
            "RuntimeReadiness",
            "FailClosed",
        )
