"""Signed, expiring, capability-bound OAuth state tests."""

from __future__ import annotations

import time

import pytest

from services.integrations.oauth.state import (
    InMemoryNonceStore,
    OAuthStateError,
    issue_state,
    verify_state,
)
from shared.integration_contracts.identity import ProviderIdentity

_IDENTITY = ProviderIdentity(family="shopify", product="admin", capability="orders_read")
_TENANT = "tenant-abc"
_REDIRECT = "https://app.example.com/oauth/callback"


def test_issue_verify_round_trip_preserves_fields() -> None:
    token = issue_state(_TENANT, _IDENTITY, _REDIRECT)
    state = verify_state(token)
    assert state.tenant_id == _TENANT
    assert state.redirect_uri == _REDIRECT
    assert state.identity == _IDENTITY
    assert state.identity.key == "shopify.admin.orders_read"
    assert state.expires_at > state.issued_at
    assert state.nonce


def test_extra_payload_is_preserved() -> None:
    token = issue_state(_TENANT, _IDENTITY, _REDIRECT, extra={"shop": "acme"})
    state = verify_state(token)
    assert state.extra == {"shop": "acme"}


def test_tampered_token_is_rejected() -> None:
    token = issue_state(_TENANT, _IDENTITY, _REDIRECT)
    encoded, signature = token.split(".", 1)
    # Flip the payload while keeping the original signature.
    other = issue_state(_TENANT, _IDENTITY, "https://evil.example.com/cb")
    forged_payload = other.split(".", 1)[0]
    forged = f"{forged_payload}.{signature}"
    with pytest.raises(OAuthStateError) as exc:
        verify_state(forged)
    assert exc.value.reason == "state_signature_invalid"


def test_signature_bitflip_is_rejected() -> None:
    token = issue_state(_TENANT, _IDENTITY, _REDIRECT)
    encoded, signature = token.split(".", 1)
    flipped = "A" if signature[0] != "A" else "B"
    with pytest.raises(OAuthStateError) as exc:
        verify_state(f"{encoded}.{flipped}{signature[1:]}")
    assert exc.value.reason == "state_signature_invalid"


def test_malformed_token_is_rejected() -> None:
    with pytest.raises(OAuthStateError) as exc:
        verify_state("not-a-valid-token")
    assert exc.value.reason == "state_malformed"


def test_expired_token_is_rejected() -> None:
    token = issue_state(_TENANT, _IDENTITY, _REDIRECT, ttl_seconds=1)
    future = int(time.time()) + 5
    with pytest.raises(OAuthStateError) as exc:
        verify_state(token, now=future)
    assert exc.value.reason == "state_expired"


def test_capability_binding_is_distinct_per_capability() -> None:
    sibling = ProviderIdentity(
        family="shopify", product="admin", capability="products_read"
    )
    token = issue_state(_TENANT, _IDENTITY, _REDIRECT)
    state = verify_state(token)
    # The bound capability is exactly the one issued — no widening to a sibling.
    assert state.identity == _IDENTITY
    assert state.identity != sibling


def test_nonce_single_use_second_consume_fails() -> None:
    store = InMemoryNonceStore()
    token = issue_state(_TENANT, _IDENTITY, _REDIRECT)
    first = verify_state(token, nonce_store=store)
    assert first.tenant_id == _TENANT
    with pytest.raises(OAuthStateError) as exc:
        verify_state(token, nonce_store=store)
    assert exc.value.reason == "state_replayed"


def test_ttl_must_be_positive() -> None:
    with pytest.raises(OAuthStateError) as exc:
        issue_state(_TENANT, _IDENTITY, _REDIRECT, ttl_seconds=0)
    assert exc.value.reason == "ttl_invalid"
