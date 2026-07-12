"""
Tests that the compliance ``ConsentPurpose`` enum stays reconciled with the
canonical 11-purpose consent registry at
``packages/shared/contracts/consent-registry.json``.

These are drift guards: if a purpose is added, removed, or has its
``explicitOptInRequired`` flag changed in the registry, the compliance enum and
config must be updated in lockstep or these tests fail.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the compliance module root is on sys.path.
_compliance_root = str(Path(__file__).resolve().parent.parent)
if _compliance_root not in sys.path:
    sys.path.insert(0, _compliance_root)

import pytest

from config.compliance_config import (
    CONSENT_CONFIG,
    EXPLICIT_OPT_IN_PURPOSES,
    LEGACY_PURPOSE_ALIASES,
    ConsentPurpose,
)
from config.consent_registry_sync import (
    ConsentRegistryError,
    assert_consent_registry_in_sync,
    canonical_keys,
    canonical_opt_in_flags,
    find_registry_path,
    reconcile,
)

EXPECTED_PURPOSE_COUNT = 11


def test_registry_is_locatable_and_has_eleven_purposes():
    """The canonical registry resolves and defines exactly 11 purposes."""
    path = find_registry_path()
    assert path.is_file(), f"registry not found at {path}"
    assert len(canonical_keys()) == EXPECTED_PURPOSE_COUNT


def test_every_canonical_key_has_a_consent_purpose_member():
    """(a) Every canonical registry key maps to a ConsentPurpose member."""
    enum_values = {p.value for p in ConsentPurpose}
    missing = [k for k in canonical_keys() if k not in enum_values]
    assert missing == [], f"canonical keys with no ConsentPurpose member: {missing}"


def test_no_uncanonical_first_class_members():
    """Every enum member is either canonical or a declared legacy alias."""
    canonical = set(canonical_keys())
    alias_keys = set(LEGACY_PURPOSE_ALIASES.keys())
    stray = sorted(
        p.value for p in ConsentPurpose
        if p.value not in canonical and p.value not in alias_keys
    )
    assert stray == [], f"non-canonical first-class purposes: {stray}"


def test_explicit_opt_in_flags_match_registry():
    """(b) Explicit-opt-in purposes are flagged consistently with the registry."""
    flags = canonical_opt_in_flags()
    for purpose in ConsentPurpose:
        if purpose.value not in flags:
            continue  # aliased/legacy member — not registry-backed
        assert purpose.requires_explicit_opt_in == flags[purpose.value], (
            f"{purpose.value}: enum requires_explicit_opt_in="
            f"{purpose.requires_explicit_opt_in} but registry "
            f"explicitOptInRequired={flags[purpose.value]}"
        )


def test_explicit_opt_in_set_is_exactly_the_registry_opt_in_purposes():
    """EXPLICIT_OPT_IN_PURPOSES equals the registry's opt-in purpose set."""
    registry_opt_in = {k for k, v in canonical_opt_in_flags().items() if v}
    enum_opt_in = {p.value for p in EXPLICIT_OPT_IN_PURPOSES}
    assert enum_opt_in == registry_opt_in


def test_consent_config_purposes_cover_all_canonical_keys():
    """CONSENT_CONFIG mirrors the enum, which mirrors the registry."""
    assert set(CONSENT_CONFIG.purposes) == set(canonical_keys())
    assert set(CONSENT_CONFIG.explicit_opt_in_purposes) == {
        k for k, v in canonical_opt_in_flags().items() if v
    }


def test_from_key_resolves_canonical_and_rejects_unknown():
    """from_key resolves canonical keys and rejects unknown keys."""
    for key in canonical_keys():
        assert ConsentPurpose.from_key(key).value == key
    with pytest.raises(ValueError):
        ConsentPurpose.from_key("definitely_not_a_purpose")


def test_reconciliation_helper_passes():
    """(c) The reconciliation helper reports in-sync and does not raise."""
    report = reconcile()
    assert report.in_sync, report.as_error_text()

    result = assert_consent_registry_in_sync()
    assert result.in_sync
    assert set(result.canonical_keys) == {p.value for p in ConsentPurpose}


def test_reconciliation_helper_detects_drift(monkeypatch):
    """The helper raises ConsentRegistryError when a canonical key is unmapped."""
    fake_keys = list(canonical_keys()) + ["__synthetic_drift_purpose__"]

    import config.consent_registry_sync as sync

    monkeypatch.setattr(sync, "canonical_keys", lambda start=None: fake_keys)
    monkeypatch.setattr(
        sync,
        "canonical_opt_in_flags",
        lambda start=None: {**canonical_opt_in_flags(), "__synthetic_drift_purpose__": False},
    )

    with pytest.raises(ConsentRegistryError):
        sync.assert_consent_registry_in_sync()
