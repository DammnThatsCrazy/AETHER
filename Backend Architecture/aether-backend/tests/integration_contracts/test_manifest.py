"""Provider manifest: a valid manifest passes; each honesty invariant rejects."""

from __future__ import annotations

import pytest

from shared.certification.readiness import CredentialReadiness
from shared.integration_contracts.manifest import (
    Accounts,
    Authentication,
    Availability,
    ConfigFieldSpec,
    Configuration,
    CredentialFieldSpec,
    Deployment,
    EnvironmentAvailability,
    ManifestReadiness,
    ManifestValidationError,
    OAuthSpec,
    ProviderManifest,
    Sync,
    Webhooks,
    validate_manifest,
)


def _valid_manifest(**overrides: object) -> ProviderManifest:
    """A fully honest manifest: staging-visible, level 4, oauth+scopes,
    verified webhook, incremental sync with a cursor."""
    base: dict[str, object] = dict(
        provider_family="shopify",
        product_id="admin",
        capability_id="orders_read",
        display_name="Shopify Orders (read)",
        category="commerce",
        readiness=ManifestReadiness(
            state=CredentialReadiness.SANDBOX_VALIDATED, level=4
        ),
        availability=Availability(
            tenant_self_service=True,
            environments=EnvironmentAvailability(
                local=True, integration=True, staging=True, production=False
            ),
        ),
        authentication=Authentication(
            type="oauth2",
            credential_schema=[
                CredentialFieldSpec(name="access_token", type="oauth_token", secret=True)
            ],
            oauth=OAuthSpec(pkce=True, scopes=["read_orders"], refresh_supported=True),
        ),
        configuration=Configuration(
            fields=[ConfigFieldSpec(name="shop_domain", type="string", required=True)]
        ),
        accounts=Accounts(discovery_supported=True, selection_required=True),
        webhooks=Webhooks(
            supported=True,
            registration_supported=True,
            verification_scheme="hmac_sha256",
        ),
        sync=Sync(initial_backfill=True, incremental=True, cursor="updated_at"),
        data_outputs=["order.created", "order.updated"],
        product_destinations=["graph", "lake"],
        deployment=Deployment(
            required_secrets=["SHOPIFY_CLIENT_SECRET"],
            required_public_urls=["https://app/oauth/callback"],
            provider_registration_steps=["Create a custom app in the Shopify admin"],
        ),
    )
    base.update(overrides)
    return ProviderManifest(**base)  # type: ignore[arg-type]


def test_valid_manifest_passes() -> None:
    m = _valid_manifest()
    assert validate_manifest(m) is m
    assert m.identity_key == "shopify.admin.orders_read"


def test_data_outputs_and_destinations_are_required_explicit() -> None:
    # They may be empty, but must be provided explicitly (no default).
    with pytest.raises(Exception):
        _valid_manifest(data_outputs=None)  # type: ignore[arg-type]
    m = _valid_manifest(data_outputs=[], product_destinations=[])
    assert validate_manifest(m) is m


def test_visible_without_level_3_rejected() -> None:
    m = _valid_manifest(
        readiness=ManifestReadiness(state=CredentialReadiness.CREDENTIAL_WAITING, level=2),
        availability=Availability(
            environments=EnvironmentAvailability(local=True, staging=False)
        ),
    )
    with pytest.raises(ManifestValidationError) as ei:
        validate_manifest(m)
    assert any("level>=3" in v for v in ei.value.violations)


def test_staging_without_level_4_rejected() -> None:
    m = _valid_manifest(
        readiness=ManifestReadiness(state=CredentialReadiness.REPLAY_VALIDATED, level=3),
        availability=Availability(
            environments=EnvironmentAvailability(staging=True)
        ),
    )
    with pytest.raises(ManifestValidationError) as ei:
        validate_manifest(m)
    assert any("staging" in v and "level>=4" in v for v in ei.value.violations)


def test_oauth_without_scopes_rejected() -> None:
    m = _valid_manifest(
        authentication=Authentication(type="oauth2", oauth=OAuthSpec(scopes=[]))
    )
    with pytest.raises(ManifestValidationError) as ei:
        validate_manifest(m)
    assert any("oauth" in v.lower() for v in ei.value.violations)

    # oauth field entirely absent is also rejected.
    m2 = _valid_manifest(authentication=Authentication(type="oauth2", oauth=None))
    with pytest.raises(ManifestValidationError):
        validate_manifest(m2)


def test_webhook_without_scheme_rejected() -> None:
    m = _valid_manifest(
        webhooks=Webhooks(supported=True, verification_scheme=None)
    )
    with pytest.raises(ManifestValidationError) as ei:
        validate_manifest(m)
    assert any("verification_scheme" in v for v in ei.value.violations)


def test_incremental_without_cursor_rejected() -> None:
    m = _valid_manifest(
        sync=Sync(initial_backfill=True, incremental=True, cursor=None)
    )
    with pytest.raises(ManifestValidationError) as ei:
        validate_manifest(m)
    assert any("cursor" in v for v in ei.value.violations)


def test_validate_collects_multiple_violations() -> None:
    m = _valid_manifest(
        readiness=ManifestReadiness(state=CredentialReadiness.CREDENTIAL_WAITING, level=1),
        availability=Availability(
            environments=EnvironmentAvailability(staging=True)
        ),
        authentication=Authentication(type="oauth2", oauth=OAuthSpec(scopes=[])),
    )
    with pytest.raises(ManifestValidationError) as ei:
        validate_manifest(m)
    # visible<3, staging<4, and oauth-without-scopes all reported at once.
    assert len(ei.value.violations) >= 3


def test_manifest_forbids_unknown_fields() -> None:
    with pytest.raises(Exception):
        _valid_manifest(unexpected_field="boom")
