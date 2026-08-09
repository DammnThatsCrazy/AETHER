"""Certification harness tests.

Drives :func:`services.provider_runtime.certification.certify_provider` against
fake plugins. The harness must never false-pass: a dishonest plugin yields
``passed=False`` with a *failing* check. No live network calls are made —
adapters receive a no-credential context.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from shared.certification.readiness import CredentialReadiness
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.identity import ProviderIdentity
from shared.integration_contracts.manifest import (
    Accounts,
    Authentication,
    Availability,
    ConfigFieldSpec,
    Configuration,
    CredentialFieldSpec,
    Deployment,
    ManifestReadiness,
    ProviderManifest,
    Sync,
    Webhooks,
)
from shared.integration_contracts.normalization import NormalizationResult
from shared.integration_contracts.results import AdapterResult, AdapterStatus

import services.provider_runtime.certification as certification


# ── Fakes ───────────────────────────────────────────────────────────────────


def make_manifest(
    *,
    family: str = "shopify",
    product: str = "products",
    capability: str = "read",
    state: CredentialReadiness = CredentialReadiness.SCAFFOLDED,
    level: int = 1,
    credential_schema: list[CredentialFieldSpec] | None = None,
    webhooks: Webhooks | None = None,
    data_outputs: list[str] | None = None,
    product_destinations: list[str] | None = None,
) -> ProviderManifest:
    return ProviderManifest(
        provider_family=family,
        product_id=product,
        capability_id=capability,
        display_name=f"{family} {product} {capability}",
        category="ecommerce",
        readiness=ManifestReadiness(state=state, level=level),
        availability=Availability(),
        authentication=Authentication(
            type="api_key",
            credential_schema=credential_schema
            or [CredentialFieldSpec(name="api_key", type="secret", required=True, secret=True)],
        ),
        configuration=Configuration(),
        accounts=Accounts(),
        webhooks=webhooks or Webhooks(),
        sync=Sync(),
        data_outputs=data_outputs or ["shopify.orders"],
        product_destinations=product_destinations or ["olympus_lake"],
        deployment=Deployment(),
    )


class _FakeNormalizer:
    def __init__(self, result=None) -> None:
        self._result = result

    def normalize(self, raw):
        if self._result is not None:
            return self._result
        return NormalizationResult(events=[], dropped=[])


class _RecordingAuth:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.contexts: list[AcquisitionContext] = []

    async def validate_credentials(self, context):
        self.contexts.append(context)
        if self.error is not None:
            raise self.error
        return self.result if self.result is not None else AdapterResult(
            success=False, status=AdapterStatus.NOT_SUPPORTED
        )


class _FakePull:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.contexts: list[AcquisitionContext] = []

    async def fetch(self, context, cursor=None):
        self.contexts.append(context)
        if self.error is not None:
            raise self.error
        return self.result if self.result is not None else AdapterResult(
            success=False, status=AdapterStatus.NOT_SUPPORTED
        )


class FakePlugin:
    def __init__(
        self,
        manifest: ProviderManifest,
        *,
        identity_key: str | None = None,
        auth=None,
        pull=None,
        webhook=None,
        normalizer=None,
        version: str = "1.0.0",
    ) -> None:
        self._manifest = manifest
        self._identity_key = identity_key or manifest.identity_key
        self._auth = auth
        self._pull = pull
        self._webhook = webhook
        self._normalizer = normalizer or _FakeNormalizer()
        self.version = version

    def identity(self) -> ProviderIdentity:
        return ProviderIdentity.parse(self._identity_key)

    def manifest(self) -> ProviderManifest:
        return self._manifest

    def auth(self):
        return self._auth

    def account(self):
        return None

    def pull(self):
        return self._pull

    def webhook(self):
        return self._webhook

    def report(self):
        return None

    def stream(self):
        return None

    def reconciliation(self):
        return None

    def normalizer(self):
        return self._normalizer


# ── Tests ───────────────────────────────────────────────────────────────────


def test_honest_plugin_passes_every_check(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(certification, "_capability_violations", lambda plugin: [])
    plugin = FakePlugin(make_manifest())

    report = certification.certify_provider(plugin)

    assert report.passed is True
    assert len(report.checks) == 10
    assert all(check.passed for check in report.checks)
    assert report.identity == "shopify.products.read"
    # Readiness is the manifest's claim VERBATIM — never upgraded.
    assert report.readiness.state == CredentialReadiness.SCAFFOLDED
    assert report.readiness.level == 1
    assert report.environment == "local"


def test_readiness_overclaim_fails(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(certification, "_capability_violations", lambda plugin: [])
    # SCAFFOLDED evidence cannot support level 5.
    plugin = FakePlugin(
        make_manifest(state=CredentialReadiness.SCAFFOLDED, level=5)
    )

    report = certification.certify_provider(plugin)

    assert report.passed is False
    check = next(c for c in report.checks if c.name == "readiness_not_overclaimed")
    assert check.passed is False
    assert "overclaims" in check.detail


def test_manifest_honesty_violation_fails(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(certification, "_capability_violations", lambda plugin: [])
    # webhooks.supported=True with no verification_scheme violates §32.
    plugin = FakePlugin(make_manifest(webhooks=Webhooks(supported=True)))

    report = certification.certify_provider(plugin)

    assert report.passed is False
    manifest_check = next(c for c in report.checks if c.name == "manifest_honest")
    assert manifest_check.passed is False
    assert "webhooks" in manifest_check.detail


def test_secret_optional_credential_field_fails(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(certification, "_capability_violations", lambda plugin: [])
    # A secret credential field may never be declared optional.
    plugin = FakePlugin(
        make_manifest(
            credential_schema=[
                CredentialFieldSpec(name="api_key", type="secret", required=False, secret=True)
            ]
        )
    )

    report = certification.certify_provider(plugin)

    assert report.passed is False
    check = next(c for c in report.checks if c.name == "credential_schema_honest")
    assert check.passed is False
    assert "optional" in check.detail


def test_identity_mismatch_fails(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(certification, "_capability_violations", lambda plugin: [])
    # Manifest says shopify.products.read; identity() says something else.
    plugin = FakePlugin(
        make_manifest(), identity_key="other.products.read"
    )

    report = certification.certify_provider(plugin)

    assert report.passed is False
    check = next(c for c in report.checks if c.name == "identity_wellformed")
    assert check.passed is False


def test_normalizer_wrong_return_fails(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(certification, "_capability_violations", lambda plugin: [])
    plugin = FakePlugin(make_manifest(), normalizer=_FakeNormalizer(result={"events": []}))

    report = certification.certify_provider(plugin)

    assert report.passed is False
    check = next(c for c in report.checks if c.name == "normalizer_roundtrip")
    assert check.passed is False
    assert "NormalizationResult" in check.detail


def test_auth_adapter_raise_is_safe(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(certification, "_capability_violations", lambda plugin: [])
    auth = _RecordingAuth(error=RuntimeError("sk_live_TOP_SECRET blew up"))
    plugin = FakePlugin(make_manifest(), auth=auth)

    report = certification.certify_provider(plugin)

    check = next(c for c in report.checks if c.name == "auth_contract")
    assert check.passed is False
    # Never leak the raw exception string into the check detail.
    assert "sk_live_TOP_SECRET" not in check.detail
    assert "blow up" not in check.detail


def test_adapters_get_no_credential_context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(certification, "_capability_violations", lambda plugin: [])
    auth = _RecordingAuth()
    pull = _FakePull()
    plugin = FakePlugin(make_manifest(), auth=auth, pull=pull)

    report = certification.certify_provider(plugin)

    assert report.passed is True
    assert len(auth.contexts) == 1
    assert len(pull.contexts) == 1
    # No-credential context: certification must never make a live network call.
    assert auth.contexts[0].credential is None
    assert pull.contexts[0].credential is None


def test_empty_output_claim_fails(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(certification, "_capability_violations", lambda plugin: [])
    plugin = FakePlugin(make_manifest(data_outputs=[""]))

    report = certification.certify_provider(plugin)

    assert report.passed is False
    check = next(c for c in report.checks if c.name == "outputs_claimed")
    assert check.passed is False


def test_webhook_scheme_requires_adapter(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(certification, "_capability_violations", lambda plugin: [])
    # manifest claims webhooks with a scheme, but no webhook adapter accessor.
    plugin = FakePlugin(
        make_manifest(webhooks=Webhooks(supported=True, verification_scheme="endpoint_secret")),
        webhook=None,
    )

    report = certification.certify_provider(plugin)

    assert report.passed is False
    check = next(c for c in report.checks if c.name == "webhook_scheme_honest")
    assert check.passed is False
    assert "adapter" in check.detail


def test_real_validation_seam_rejects_dishonest_plugin():
    """End-to-end through the REAL validation module (no monkeypatch).

    A plugin that claims webhooks but exposes no adapter must be caught by the
    capability-honesty check via Team A's actual ``capability_violations`` —
    proving the harness fails honestly with the seam in place, not just against
    an injected fake.
    """
    try:
        import services.provider_runtime.validation  # noqa: F401
    except ImportError:
        pytest.skip("blocked on Team A: services.provider_runtime.validation not landed")

    plugin = FakePlugin(
        make_manifest(webhooks=Webhooks(supported=True, verification_scheme="endpoint_secret")),
        webhook=None,
    )

    report = certification.certify_provider(plugin)

    assert report.passed is False
    cap_check = next(c for c in report.checks if c.name == "capability_honest")
    assert cap_check.passed is False
    assert "webhook" in cap_check.detail


def test_capability_honest_delegates_to_validation_when_landed(monkeypatch: pytest.MonkeyPatch):
    """The harness must consult Team A's real validator once it lands.

    Until ``services.provider_runtime.validation`` exists this is honestly
    skipped; the harness then fails the capability_honest check (import raises).
    """
    try:
        from services.provider_runtime.validation import capability_violations  # noqa: F401
    except ImportError:
        pytest.skip("blocked on Team A: services.provider_runtime.validation not landed")

    plugin = FakePlugin(make_manifest())
    violations = capability_violations(plugin)
    assert isinstance(violations, list)


def test_capability_honest_overclaim_fails_when_validation_absent(monkeypatch):
    """When Team A's validator is not installed the check must fail loudly —
    never a silent pass."""
    monkeypatch.setattr(certification, "_capability_violations", _import_error_violations)

    plugin = FakePlugin(make_manifest())
    report = certification.certify_provider(plugin)

    check = next(c for c in report.checks if c.name == "capability_honest")
    assert check.passed is False


def _import_error_violations(plugin):
    raise ImportError("services.provider_runtime.validation is not installed")
