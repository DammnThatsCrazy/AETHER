"""Consent enforcement must derive its purpose set from the canonical registry.

Regression guard for the pre-8.12.0 defect where
shared/privacy/consent_enforcement.py hardcoded a stale purpose set that was
missing `financial_activity` (added by derivatives PR1) — silently breaking
purpose validation for any registry-added purpose.
"""

from __future__ import annotations

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
REGISTRY = REPO_ROOT / "packages" / "shared" / "contracts" / "consent-registry.json"

sys.path.insert(0, str(BACKEND))

from shared.privacy.consent_enforcement import (  # noqa: E402
    CONSENT_PURPOSES,
    is_consent_required_purpose,
)


def _registry_purposes() -> list[dict]:
    return json.loads(REGISTRY.read_text())["purposes"]


def test_consent_purposes_match_registry_exactly() -> None:
    registry_keys = {p["key"] for p in _registry_purposes()}
    assert CONSENT_PURPOSES == registry_keys


def test_new_domain_purposes_are_present() -> None:
    for purpose in ("financial_activity", "economic_observability", "cross_chain_observability"):
        assert purpose in CONSENT_PURPOSES


def test_consent_required_follows_registry_default_enabled() -> None:
    for purpose in _registry_purposes():
        expected = not purpose.get("defaultEnabled", False)
        assert is_consent_required_purpose(purpose["key"]) is expected, purpose["key"]


def test_default_enabled_purposes_are_not_consent_required() -> None:
    # analytics is the platform's only default-enabled purpose today.
    assert not is_consent_required_purpose("analytics")
