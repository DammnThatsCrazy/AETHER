"""Tests for the typed provider-runtime error hierarchy."""

from __future__ import annotations

import pytest

from services.provider_runtime.errors import (
    AccountSelectionRequired,
    AuthorizationFailed,
    ConnectionStateViolation,
    CredentialMissing,
    CursorInvalid,
    ManifestInvalid,
    NormalizationFailed,
    PermissionMissing,
    PluginIncompatible,
    ProviderConfigurationInvalid,
    ProviderNotInstalled,
    ProviderPullFailed,
    ProviderRateLimited,
    ProviderReportFailed,
    ProviderRuntimeError,
    ProviderUnavailable,
    ReconciliationFailed,
    WebhookVerificationFailed,
)

ALL_ERROR_TYPES = [
    ProviderNotInstalled,
    ManifestInvalid,
    PluginIncompatible,
    CredentialMissing,
    AuthorizationFailed,
    PermissionMissing,
    AccountSelectionRequired,
    ProviderConfigurationInvalid,
    WebhookVerificationFailed,
    ProviderRateLimited,
    ProviderUnavailable,
    ProviderPullFailed,
    ProviderReportFailed,
    NormalizationFailed,
    ReconciliationFailed,
    CursorInvalid,
    ConnectionStateViolation,
]


def test_all_subclasses_are_provider_runtime_error():
    for err_type in ALL_ERROR_TYPES:
        assert issubclass(err_type, ProviderRuntimeError)
        assert issubclass(err_type, ValueError)


@pytest.mark.parametrize("err_type", ALL_ERROR_TYPES)
def test_each_type_constructs_with_details(err_type):
    err = err_type("boom", details={"connection_id": "c1", "provider": "shopify"})
    assert isinstance(err, ProviderRuntimeError)
    assert err.safe_message == "boom"
    assert err.details == {"connection_id": "c1", "provider": "shopify"}


def test_safe_message_excludes_details():
    err = ProviderRuntimeError(
        "credentials for tenant rejected",
        details={"secret": "sk_live_abc", "correlation_id": "corr-123"},
    )
    # safe_message is the message only — never the details dict.
    assert err.safe_message == "credentials for tenant rejected"
    assert "sk_live_abc" not in err.safe_message
    assert "corr-123" not in err.safe_message


def test_details_default_to_empty_dict():
    err = ProviderRateLimited("rate limited")
    assert err.details == {}
    assert err.safe_message == "rate limited"


def test_error_message_round_trip_via_str():
    err = CursorInvalid("cursor malformed")
    assert str(err) == "cursor malformed"
    assert isinstance(err, ValueError)
