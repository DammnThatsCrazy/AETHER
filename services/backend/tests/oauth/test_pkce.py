"""PKCE (RFC 7636, S256) unit tests."""

from __future__ import annotations

import base64
import hashlib

import pytest

from services.integrations.oauth.pkce import (
    MAX_VERIFIER_LENGTH,
    MIN_VERIFIER_LENGTH,
    compute_challenge,
    generate_pkce,
    verify_pkce,
)


def _expected_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def test_challenge_is_base64url_sha256_of_verifier() -> None:
    pair = generate_pkce()
    assert pair.method == "S256"
    assert pair.challenge == _expected_challenge(pair.verifier)
    # base64url, no padding.
    assert "=" not in pair.challenge
    assert "+" not in pair.challenge and "/" not in pair.challenge


def test_verify_true_for_matching_pair() -> None:
    pair = generate_pkce()
    assert verify_pkce(pair.verifier, pair.challenge) is True


def test_verify_false_for_mismatch() -> None:
    a = generate_pkce()
    b = generate_pkce()
    assert verify_pkce(a.verifier, b.challenge) is False


def test_generated_verifier_within_rfc_length_bounds() -> None:
    for _ in range(20):
        pair = generate_pkce()
        assert MIN_VERIFIER_LENGTH <= len(pair.verifier) <= MAX_VERIFIER_LENGTH


@pytest.mark.parametrize("bad", ["", "short", "x" * 42, "y" * 129, "has space!!" * 5])
def test_compute_challenge_rejects_out_of_bounds_verifier(bad: str) -> None:
    with pytest.raises(ValueError):
        compute_challenge(bad)


def test_verify_false_for_invalid_verifier_never_raises() -> None:
    assert verify_pkce("too-short", "anything") is False
    assert verify_pkce("z" * 43, "not-the-challenge") is False
