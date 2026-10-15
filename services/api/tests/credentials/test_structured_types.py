"""Structured credential shapes: parsing, secret hygiene, expiry."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from shared.credentials.types import (
    ApiKeyCredential,
    ApiKeyWebhookSecretCredential,
    ClientSecretCredential,
    KeyIdSecretCredential,
    KeypairCredential,
    MultiCredential,
    OAuthTokenCredential,
    ServiceAccountCredential,
    UsernameTokenCredential,
    as_structured,
    from_plaintext_dict,
    masked_identifier,
    masked_metadata,
    to_plaintext_dict,
)

_FAKE = "sk-test-0000"


def _all_shapes():
    return [
        ApiKeyCredential(api_key=_FAKE),
        ClientSecretCredential(client_id="cid-0000", client_secret=_FAKE),
        OAuthTokenCredential(access_token=_FAKE, refresh_token="rt-test-0000", scope=["read"]),
        KeyIdSecretCredential(key_id="kid-0000", secret=_FAKE),
        KeypairCredential(public_key="pub-0000", private_key=_FAKE),
        ServiceAccountCredential(service_account_json='{"k":"v"}', client_email="a@b.test"),
        UsernameTokenCredential(username="u0000", token=_FAKE),
        ApiKeyWebhookSecretCredential(api_key=_FAKE, webhook_secret="whsec-test-0000"),
        MultiCredential(credentials={"primary": ApiKeyCredential(api_key=_FAKE)}),
    ]


def test_all_shapes_parse_via_discriminator():
    for cred in _all_shapes():
        dumped = to_plaintext_dict(cred)
        assert dumped["type"] == cred.type
        rebuilt = from_plaintext_dict(dumped)
        assert rebuilt.type == cred.type


@pytest.mark.parametrize("cred", _all_shapes())
def test_secretstr_never_leaks(cred):
    """SecretStr must not surface in repr / model_dump / model_dump_json."""
    assert _FAKE not in repr(cred)
    assert _FAKE not in str(cred.model_dump())
    assert _FAKE not in cred.model_dump_json()


def test_as_structured_bare_string_is_api_key():
    cred = as_structured("some-key-0000")
    assert isinstance(cred, ApiKeyCredential)
    assert cred.api_key.get_secret_value() == "some-key-0000"


def test_as_structured_passthrough():
    original = ClientSecretCredential(client_id="cid", client_secret=_FAKE)
    assert as_structured(original) is original


def test_is_expired_true_and_false():
    past = ApiKeyCredential(api_key=_FAKE, expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    future = ApiKeyCredential(api_key=_FAKE, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    none = ApiKeyCredential(api_key=_FAKE)
    assert past.is_expired() is True
    assert future.is_expired() is False
    assert none.is_expired() is False


def test_reveal_accessor_is_explicit():
    cred = ApiKeyCredential(api_key=_FAKE)
    assert cred.api_key.get_secret_value() == _FAKE


def test_masked_helpers_carry_no_secret():
    cred = ClientSecretCredential(client_id="cid-visible", client_secret=_FAKE)
    ident = masked_identifier(cred)
    assert ident.startswith("****")
    assert len(ident) == 8
    assert _FAKE not in ident
    md = masked_metadata(cred)
    assert md["credential_type"] == "client_secret"
    assert md["client_id"] == "cid-visible"  # non-secret display is allowed
    assert _FAKE not in str(md)
