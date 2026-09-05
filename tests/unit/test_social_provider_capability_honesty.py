"""M2-A social-capability honesty gate tests (UPR social vocabulary).

Covers the social-scoped validator
``services.provider_runtime.social_capability.social_capability_violations`` and
its wiring into ``services.provider_runtime.validation.capability_violations``
(so it runs on ``registry.register``):

* a social plugin whose capability segment is outside the canonical vocabulary
  is caught (fail-closed);
* a social plugin with a non-well-formed identity grammar is caught;
* a social plugin claiming ``partner_live`` without external certification
  evidence is caught, and is admitted when a passed ``CertificationReport`` with
  ``readiness.state == PARTNER_LIVE`` is attached (reused enums — no new ones);
* lower / blocked states (``credential_waiting`` ...) are never flagged;
* commerce plugins (``product != "social"``) trigger zero new violations
  (regression guard) even when they claim ``partner_live``;
* a broken plugin never makes the social gate raise.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# Force the WORKTREE backend onto sys.path ahead of any editable install so the
# `shared` / `services` imports below resolve to THIS checkout.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest

from shared.certification.readiness import CredentialReadiness
from shared.integration_contracts.certification import (
    CertificationCheck,
    CertificationReport,
)
from shared.integration_contracts.identity import ProviderIdentity
from shared.integration_contracts.manifest import (
    Authentication,
    Availability,
    ManifestReadiness,
    ProviderManifest,
)
from shared.integration_contracts.plugin import PluginValidationError

from services.provider_runtime.plugin import BaseProviderPlugin
from services.provider_runtime.registry import ProviderRegistry
from services.provider_runtime.social_capability import social_capability_violations
from services.provider_runtime.validation import capability_violations


def _manifest(
    *,
    family: str = "reddit",
    product: str = "social",
    capability: str = "account_read",
    state: CredentialReadiness = CredentialReadiness.CREDENTIAL_WAITING,
    level: int = 2,
) -> ProviderManifest:
    return ProviderManifest(
        provider_family=family,
        product_id=product,
        capability_id=capability,
        display_name=f"{family.title()} Social",
        category="social",
        readiness=ManifestReadiness(state=state, level=level),
        availability=Availability(),
        authentication=Authentication(type="none"),
        data_outputs=["social.raw_events"],
        product_destinations=[],
    )


class _SocialPlugin(BaseProviderPlugin):
    """A minimal honest social plugin: no adapter accessors are claimed (the
    base defaults every capability accessor to ``None``)."""

    abi_version = "1"

    def __init__(
        self,
        *,
        capability: str = "account_read",
        state: CredentialReadiness = CredentialReadiness.CREDENTIAL_WAITING,
        level: int = 2,
        family: str = "reddit",
        report=None,
    ) -> None:
        self._capability = capability
        self._state = state
        self._level = level
        self._family = family
        self._report = report

    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(
            family=self._family, product="social", capability=self._capability
        )

    def manifest(self) -> ProviderManifest:
        return _manifest(
            family=self._family,
            product="social",
            capability=self._capability,
            state=self._state,
            level=self._level,
        )

    def normalizer(self) -> None:
        return None

    @property
    def certification_report(self):
        return self._report


def _report(
    *, identity: str = "reddit.social.account_read",
    state: CredentialReadiness = CredentialReadiness.PARTNER_LIVE,
    level: int = 5,
    passed: bool = True,
) -> CertificationReport:
    return CertificationReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        identity=identity,
        readiness=ManifestReadiness(state=state, level=level),
        checks=[CertificationCheck(name="readiness_not_overclaimed", passed=passed)],
        passed=passed,
    )


# ── (a) capability membership ───────────────────────────────────────────────


def test_social_capability_outside_vocabulary_is_caught():
    plugin = _SocialPlugin(capability="bestie_read")
    violations = social_capability_violations(plugin)
    assert any("outside the canonical vocabulary" in v for v in violations)
    assert any("bestie_read" in v for v in violations)


def test_social_capability_outside_vocabulary_fails_registration():
    registry = ProviderRegistry(auto_install_legacy=False)
    with pytest.raises(PluginValidationError) as excinfo:
        registry.register(_SocialPlugin(capability="relationship_watch"))
    assert any("outside the canonical vocabulary" in v for v in excinfo.value.violations)


# ── (b) grammar well-formedness ─────────────────────────────────────────────


def test_social_identity_bad_grammar_is_caught():
    class _BadGrammarPlugin(_SocialPlugin):
        def identity(self):
            # Non-ProviderIdentity duck type so a malformed family can reach the
            # grammar check (ProviderIdentity would reject it at construction).
            return SimpleNamespace(product="social", key="Reddit.social.account_read")

    violations = social_capability_violations(_BadGrammarPlugin())
    assert any("not well-formed" in v for v in violations)


# ── (d) partner_live lifecycle honesty ──────────────────────────────────────


def test_social_partner_live_without_evidence_is_caught():
    plugin = _SocialPlugin(state=CredentialReadiness.PARTNER_LIVE, level=5)
    violations = social_capability_violations(plugin)
    assert any("partner_live" in v and "external evidence" in v for v in violations)


def test_social_partner_live_without_evidence_fails_registration():
    registry = ProviderRegistry(auto_install_legacy=False)
    plugin = _SocialPlugin(state=CredentialReadiness.PARTNER_LIVE, level=5)
    with pytest.raises(PluginValidationError) as excinfo:
        registry.register(plugin)
    assert any("partner_live" in v for v in excinfo.value.violations)


def test_social_partner_live_with_passed_evidence_is_admitted():
    report = _report(state=CredentialReadiness.PARTNER_LIVE, level=5)
    plugin = _SocialPlugin(
        state=CredentialReadiness.PARTNER_LIVE, level=5, report=report
    )
    violations = social_capability_violations(plugin)
    assert not any("partner_live" in v for v in violations)
    # and it registers cleanly end-to-end
    registry = ProviderRegistry(auto_install_legacy=False)
    assert registry.register(plugin) == "reddit.social.account_read"


def test_social_partner_live_evidence_that_is_not_partner_live_is_caught():
    report = _report(state=CredentialReadiness.SANDBOX_VALIDATED, level=4, passed=True)
    plugin = _SocialPlugin(
        state=CredentialReadiness.PARTNER_LIVE, level=5, report=report
    )
    violations = social_capability_violations(plugin)
    assert any("does not evidence partner_live" in v for v in violations)


def test_social_partner_live_failed_report_is_caught():
    report = _report(state=CredentialReadiness.PARTNER_LIVE, level=5, passed=False)
    plugin = _SocialPlugin(
        state=CredentialReadiness.PARTNER_LIVE, level=5, report=report
    )
    violations = social_capability_violations(plugin)
    assert any("does not evidence partner_live" in v for v in violations)


def test_social_low_states_are_never_flagged():
    # credential_waiting / sandbox_validated are honest, non-defect states.
    for state, level in (
        (CredentialReadiness.CREDENTIAL_WAITING, 2),
        (CredentialReadiness.SANDBOX_VALIDATED, 4),
        (CredentialReadiness.REPLAY_VALIDATED, 3),
    ):
        plugin = _SocialPlugin(state=state, level=level)
        assert social_capability_violations(plugin) == []
        assert capability_violations(plugin) == []


# ── honest social plugin baseline ───────────────────────────────────────────


def test_honest_social_plugin_has_no_violations_and_registers():
    plugin = _SocialPlugin()
    assert social_capability_violations(plugin) == []
    assert capability_violations(plugin) == []
    registry = ProviderRegistry(auto_install_legacy=False)
    assert registry.register(plugin) == "reddit.social.account_read"


# ── (iii) commerce plugins are completely unaffected ────────────────────────


def test_commerce_plugin_triggers_zero_social_violations():
    # A real commerce plugin (product == "shop") must stay clean now that the
    # social gate is wired into capability_violations.
    from services.providers.shopify.plugin import ShopifyOrdersPlugin

    plugin = ShopifyOrdersPlugin()
    assert social_capability_violations(plugin) == []
    assert capability_violations(plugin) == []


def test_commerce_plugin_partner_live_is_unaffected():
    # Commerce plugins claiming partner_live with NO evidence must not be
    # touched by the social-scoped gate (they are outside the vocabulary scope).
    class _ShopPlugin(_SocialPlugin):
        def identity(self) -> ProviderIdentity:
            return ProviderIdentity(
                family="shopify", product="shop", capability="orders_read"
            )

        def manifest(self) -> ProviderManifest:
            return _manifest(
                family="shopify",
                product="shop",
                capability="orders_read",
                state=CredentialReadiness.PARTNER_LIVE,
                level=5,
            )

    plugin = _ShopPlugin()
    assert social_capability_violations(plugin) == []
    assert capability_violations(plugin) == []


# ── fail-closed: the gate never raises for a broken plugin ──────────────────


def test_social_gate_never_raises_for_broken_identity():
    class _BrokenIdentityPlugin(_SocialPlugin):
        def identity(self):
            raise RuntimeError("identity factory exploded")

    # Direct gate: a broken identity cannot be proven social → empty list (the
    # base §32 path reports the raising accessor).
    assert social_capability_violations(_BrokenIdentityPlugin()) == []
    # Full path: the raising accessor is a violation, never a silent pass.
    violations = capability_violations(_BrokenIdentityPlugin())
    assert any("identity" in v and ("raised" in v or "exploded" in v) for v in violations)


def test_social_gate_reports_violations_as_strings_not_raises():
    plugin = _SocialPlugin(capability="bestie_read", state=CredentialReadiness.PARTNER_LIVE, level=5)
    violations = social_capability_violations(plugin)  # must not raise
    assert all(isinstance(v, str) for v in violations)
    assert len(violations) >= 2
