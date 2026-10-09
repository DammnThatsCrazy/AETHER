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
from shared.integration_contracts.streams import StreamDescriptor
from shared.privacy.classification import DataClassification


def _valid_manifest(**overrides: object) -> ProviderManifest:
    """A fully honest manifest: staging-visible, level 4, oauth+scopes,
    verified webhook, incremental sync with a cursor."""
    base: dict[str, object] = dict(
        provider_family="shopify",
        product_id="admin",
        capability_id="orders_read",
        display_name="Shopify Orders (read)",
        category="commerce",
        readiness=ManifestReadiness(state=CredentialReadiness.SANDBOX_VALIDATED, level=4),
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
        availability=Availability(environments=EnvironmentAvailability(local=True, staging=False)),
    )
    with pytest.raises(ManifestValidationError) as ei:
        validate_manifest(m)
    assert any("level>=3" in v for v in ei.value.violations)


def test_staging_without_level_4_rejected() -> None:
    m = _valid_manifest(
        readiness=ManifestReadiness(state=CredentialReadiness.REPLAY_VALIDATED, level=3),
        availability=Availability(environments=EnvironmentAvailability(staging=True)),
    )
    with pytest.raises(ManifestValidationError) as ei:
        validate_manifest(m)
    assert any("staging" in v and "level>=4" in v for v in ei.value.violations)


def test_oauth_without_scopes_rejected() -> None:
    m = _valid_manifest(authentication=Authentication(type="oauth2", oauth=OAuthSpec(scopes=[])))
    with pytest.raises(ManifestValidationError) as ei:
        validate_manifest(m)
    assert any("oauth" in v.lower() for v in ei.value.violations)

    # oauth field entirely absent is also rejected.
    m2 = _valid_manifest(authentication=Authentication(type="oauth2", oauth=None))
    with pytest.raises(ManifestValidationError):
        validate_manifest(m2)


def test_webhook_without_scheme_rejected() -> None:
    m = _valid_manifest(webhooks=Webhooks(supported=True, verification_scheme=None))
    with pytest.raises(ManifestValidationError) as ei:
        validate_manifest(m)
    assert any("verification_scheme" in v for v in ei.value.violations)


def test_incremental_without_cursor_rejected() -> None:
    m = _valid_manifest(sync=Sync(initial_backfill=True, incremental=True, cursor=None))
    with pytest.raises(ManifestValidationError) as ei:
        validate_manifest(m)
    assert any("cursor" in v for v in ei.value.violations)


def test_validate_collects_multiple_violations() -> None:
    m = _valid_manifest(
        readiness=ManifestReadiness(state=CredentialReadiness.CREDENTIAL_WAITING, level=1),
        availability=Availability(environments=EnvironmentAvailability(staging=True)),
        authentication=Authentication(type="oauth2", oauth=OAuthSpec(scopes=[])),
    )
    with pytest.raises(ManifestValidationError) as ei:
        validate_manifest(m)
    # visible<3, staging<4, and oauth-without-scopes all reported at once.
    assert len(ei.value.violations) >= 3


def test_manifest_forbids_unknown_fields() -> None:
    with pytest.raises(Exception):
        _valid_manifest(unexpected_field="boom")


def _orders_stream(**overrides: object) -> StreamDescriptor:
    values: dict[str, object] = dict(
        stream_id="orders",
        object_kind="order",
        domain_pack="commerce",
        acquisition_modes=("pull", "webhook"),
        output_contract="order.updated",
        source_authority_class="commerce_order",
        data_classification=DataClassification.SENSITIVE_PII,
        required_scopes=("read_orders",),
        cursor_scheme="updated_at_and_id",
        webhook_topics=("orders/create", "orders/updated"),
        initial_backfill=True,
        incremental=True,
    )
    values.update(overrides)
    return StreamDescriptor(**values)  # type: ignore[arg-type]


def test_versioned_stream_matches_manifest_capabilities() -> None:
    stream = _orders_stream()
    manifest = _valid_manifest(streams=[stream], sync=Sync(initial_backfill=True, incremental=True))
    assert validate_manifest(manifest) is manifest
    assert manifest.streams == [stream]
    assert stream.schema_version == "1"


def test_stream_activation_value_must_be_declared_by_manifest_config() -> None:
    stream = _orders_stream(
        activation_config_field="orders_api",
        activation_config_value="graphql",
    )
    configuration = Configuration(
        fields=[
            ConfigFieldSpec(
                name="orders_api",
                type="enum",
                allowed_values=["rest", "graphql"],
                default_value="rest",
            )
        ]
    )
    manifest = _valid_manifest(
        configuration=configuration,
        streams=[stream],
        sync=Sync(initial_backfill=True, incremental=True),
    )
    assert validate_manifest(manifest) is manifest

    undeclared_value = _valid_manifest(
        configuration=configuration,
        streams=[
            _orders_stream(
                activation_config_field="orders_api",
                activation_config_value="private_api",
            )
        ],
        sync=Sync(initial_backfill=True, incremental=True),
    )
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest(undeclared_value)
    assert any("activation value" in violation for violation in excinfo.value.violations)


def test_stream_activation_rejects_missing_or_ambiguous_config_field() -> None:
    stream = _orders_stream(
        activation_config_field="orders_api",
        activation_config_value="graphql",
    )
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest(
            _valid_manifest(
                streams=[stream],
                sync=Sync(initial_backfill=True, incremental=True),
            )
        )
    assert any("activation references undeclared" in v for v in excinfo.value.violations)

    duplicate_config = Configuration(
        fields=[
            ConfigFieldSpec(name="orders_api", type="enum", allowed_values=["graphql"]),
            ConfigFieldSpec(name="orders_api", type="enum", allowed_values=["graphql"]),
        ]
    )
    with pytest.raises(ManifestValidationError) as duplicate_excinfo:
        validate_manifest(
            _valid_manifest(
                configuration=duplicate_config,
                streams=[stream],
                sync=Sync(initial_backfill=True, incremental=True),
            )
        )
    assert any(
        "activation references undeclared or ambiguous" in v
        for v in duplicate_excinfo.value.violations
    )


def test_stream_activation_condition_fields_must_be_declared_together() -> None:
    with pytest.raises(Exception, match="must be declared together"):
        _orders_stream(activation_config_field="orders_api")


def test_unsupported_stream_schema_version_is_rejected() -> None:
    with pytest.raises(Exception):
        _orders_stream(schema_version="2")


@pytest.mark.parametrize(
    ("stream_overrides", "needle"),
    [
        ({"cursor_scheme": None}, "cursor_scheme"),
        ({"webhook_topics": ()}, "webhook_topics"),
        ({"required_scopes": ("read_customers",)}, "undeclared oauth scopes"),
        ({"output_contract": "order.deleted"}, "absent from data_outputs"),
        ({"acquisition_modes": ("webhook",)}, "sync without an acquisition adapter"),
        ({"acquisition_modes": ("pull", "pull", "webhook")}, "repeats an acquisition mode"),
    ],
)
def test_stream_declaration_rejects_false_claims(
    stream_overrides: dict[str, object], needle: str
) -> None:
    manifest = _valid_manifest(streams=[_orders_stream(**stream_overrides)])
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest(manifest)
    assert any(needle in violation for violation in excinfo.value.violations)


def test_stream_ids_and_webhook_topics_are_unambiguous() -> None:
    duplicate_id = _valid_manifest(streams=[_orders_stream(), _orders_stream()])
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest(duplicate_id)
    assert any("duplicate stream_id" in v for v in excinfo.value.violations)

    duplicate_topic = _valid_manifest(
        streams=[
            _orders_stream(),
            _orders_stream(stream_id="draft_orders", webhook_topics=("orders/create",)),
        ]
    )
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest(duplicate_topic)
    assert any("ambiguous" in v for v in excinfo.value.violations)


def test_explicit_streams_must_cover_aggregate_capabilities() -> None:
    missing_webhook = _valid_manifest(
        streams=[_orders_stream(acquisition_modes=("pull",), webhook_topics=())]
    )
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest(missing_webhook)
    assert any("webhooks.supported" in v for v in excinfo.value.violations)

    missing_backfill = _valid_manifest(streams=[_orders_stream(initial_backfill=False)])
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest(missing_backfill)
    assert any("sync.initial_backfill" in v for v in excinfo.value.violations)


def test_non_oauth_stream_cannot_claim_oauth_scopes() -> None:
    manifest = _valid_manifest(
        authentication=Authentication(type="api_key"),
        streams=[_orders_stream()],
    )
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest(manifest)
    assert any("authentication is not oauth2" in v for v in excinfo.value.violations)


def test_report_based_backfill_does_not_require_pull() -> None:
    report_stream = _orders_stream(
        acquisition_modes=("report",),
        webhook_topics=(),
        incremental=False,
        cursor_scheme=None,
    )
    manifest = _valid_manifest(
        streams=[report_stream],
        sync=Sync(initial_backfill=True),
        webhooks=Webhooks(),
    )
    assert validate_manifest(manifest) is manifest
