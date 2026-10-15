"""Alternative credential modes preserve v1 strictness and Shopify honesty."""

from __future__ import annotations

import pytest

from connectors.provider_runtime.certification import certify_provider
from connectors.providers.shopify.plugin import ShopifyOrdersPlugin
from shared.integration_contracts.manifest import (
    ConfigFieldSpec,
    CredentialFieldSpec,
    CredentialProfileSpec,
    ManifestValidationError,
    validate_manifest,
)


def test_shopify_pull_and_webhook_profiles_are_complete_and_certified() -> None:
    plugin = ShopifyOrdersPlugin()
    manifest = plugin.manifest()
    validate_manifest(manifest)
    assert {
        p.mode_value: set(p.required_fields) for p in manifest.authentication.credential_profiles
    } == {
        "rest": {"api_key", "password"},
        "rest_webhook": {"api_key", "password", "webhook_secret"},
        "graphql": {"shop_access_token"},
    }
    assert manifest.readiness.state.value == "credential_waiting"
    assert manifest.readiness.level == 2
    assert manifest.availability.environments.any_enabled() is False
    report = certify_provider(plugin)
    assert report.passed is True
    assert report.readiness == manifest.readiness


@pytest.mark.parametrize(
    "change,needle",
    [
        (
            lambda m: m.model_copy(
                update={
                    "configuration": m.configuration.model_copy(
                        update={
                            "fields": [
                                ConfigFieldSpec(
                                    name="orders_api",
                                    type="enum",
                                    allowed_values=["rest", "graphql", "uncovered"],
                                    default_value="rest",
                                ),
                                *[f for f in m.configuration.fields if f.name != "orders_api"],
                            ]
                        }
                    ),
                }
            ),
            "without a credential profile",
        ),
        (
            lambda m: m.model_copy(
                update={
                    "authentication": m.authentication.model_copy(
                        update={
                            "credential_profiles": [
                                *m.authentication.credential_profiles,
                                CredentialProfileSpec(
                                    name="duplicate",
                                    mode_field="orders_api",
                                    mode_value="rest",
                                    required_fields=["api_key"],
                                ),
                            ]
                        }
                    ),
                }
            ),
            "repeated mode",
        ),
        (
            lambda m: m.model_copy(
                update={
                    "authentication": m.authentication.model_copy(
                        update={
                            "credential_profiles": [
                                CredentialProfileSpec(
                                    name="rest_basic",
                                    mode_field="orders_api",
                                    mode_value="rest",
                                    required_fields=["missing_secret"],
                                ),
                                m.authentication.credential_profiles[1],
                            ]
                        }
                    ),
                }
            ),
            "undeclared field",
        ),
    ],
)
def test_malformed_credential_profiles_fail_manifest_validation(change, needle: str) -> None:
    manifest = change(ShopifyOrdersPlugin().manifest())
    with pytest.raises(ManifestValidationError, match=needle):
        validate_manifest(manifest)


def test_optional_secret_must_be_in_a_declared_profile() -> None:
    class UncoveredSecretPlugin(ShopifyOrdersPlugin):
        def manifest(self):
            manifest = super().manifest()
            authentication = manifest.authentication.model_copy(
                update={
                    "credential_schema": [
                        *manifest.authentication.credential_schema,
                        CredentialFieldSpec(
                            name="uncovered_secret",
                            type="secret",
                            required=False,
                            secret=True,
                        ),
                    ]
                }
            )
            return manifest.model_copy(update={"authentication": authentication})

    report = certify_provider(UncoveredSecretPlugin())
    check = next(c for c in report.checks if c.name == "credential_schema_honest")
    assert report.passed is False
    assert check.passed is False
    assert "uncovered_secret" in check.detail


def test_v1_manifest_without_profiles_keeps_required_secret_rule() -> None:
    class NoProfilesPlugin(ShopifyOrdersPlugin):
        def manifest(self):
            manifest = super().manifest()
            authentication = manifest.authentication.model_copy(update={"credential_profiles": []})
            return manifest.model_copy(update={"authentication": authentication})

    report = certify_provider(NoProfilesPlugin())
    check = next(c for c in report.checks if c.name == "credential_schema_honest")
    assert report.passed is False
    assert check.passed is False
    assert "optional" in check.detail
