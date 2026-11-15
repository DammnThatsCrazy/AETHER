"""Correlation tokens: tenant-bound, identity-free, fail-closed."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from shared.integration_contracts.correlation_token import (
    MAX_TOKEN_LENGTH,
    extract_correlation_tokens,
    issue_correlation_token,
    token_verifier,
    verify_correlation_token,
)

KEY = b"k" * 32
KEYS = {"k1": KEY}
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def _issue(**kw: object):
    params: dict[str, object] = dict(tenant_id="tenant_a", key_id="k1", secret=KEY, now=NOW)
    params.update(kw)
    return issue_correlation_token(**params)  # type: ignore[arg-type]


def test_round_trip() -> None:
    issued = _issue()
    result = verify_correlation_token(issued.token, tenant_id="tenant_a", keys=KEYS, now=NOW)
    assert result.valid and result.task_ref == issued.task_ref and result.key_id == "k1"
    assert len(issued.token) <= MAX_TOKEN_LENGTH


def test_payload_carries_no_tenant_or_identity() -> None:
    issued = _issue(tenant_id="tenant_secret_name")
    payload_b64 = issued.token.split(".")[1]
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
    assert set(payload) == {"e", "i", "k", "t", "v"}
    assert "tenant_secret_name" not in issued.token


def test_wrong_tenant_never_verifies() -> None:
    issued = _issue()
    result = verify_correlation_token(issued.token, tenant_id="tenant_b", keys=KEYS, now=NOW)
    assert not result.valid and result.rejection == "bad_signature" and result.task_ref is None


def test_expiry_and_future_issue() -> None:
    issued = _issue(ttl=timedelta(hours=1))
    later = NOW + timedelta(hours=1)
    assert verify_correlation_token(issued.token, tenant_id="tenant_a", keys=KEYS, now=later).rejection == "expired"
    early = NOW - timedelta(minutes=10)
    assert (
        verify_correlation_token(issued.token, tenant_id="tenant_a", keys=KEYS, now=early).rejection
        == "not_yet_valid"
    )


def test_key_rotation_and_unknown_key() -> None:
    issued = _issue(key_id="k2", secret=b"z" * 32)
    assert verify_correlation_token(issued.token, tenant_id="tenant_a", keys=KEYS, now=NOW).rejection == "unknown_key"
    rotated = {"k1": KEY, "k2": b"z" * 32}
    assert verify_correlation_token(issued.token, tenant_id="tenant_a", keys=rotated, now=NOW).valid


@pytest.mark.parametrize(
    "token",
    ["", "aet1", "aet1.a.b", "aet2.xx.yy", "aet1.!!!.sig", "x" * 400, "aet1.e30." + "A" * 43],
)
def test_malformed_tokens_fail_closed(token: str) -> None:
    result = verify_correlation_token(token, tenant_id="tenant_a", keys=KEYS, now=NOW)
    assert not result.valid and result.rejection == "malformed"


def test_tampered_payload_fails() -> None:
    issued = _issue()
    prefix, payload_b64, sig = issued.token.split(".")
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
    payload["e"] += 86400
    forged = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    token = f"{prefix}.{forged.rstrip(b'=').decode()}.{sig}"
    assert verify_correlation_token(token, tenant_id="tenant_a", keys=KEYS, now=NOW).rejection == "bad_signature"


def test_issue_rejects_weak_inputs() -> None:
    with pytest.raises(ValueError):
        _issue(secret=b"short")
    with pytest.raises(ValueError):
        _issue(tenant_id=" ")
    with pytest.raises(ValueError):
        _issue(ttl=timedelta(days=31))
    with pytest.raises(ValueError):
        _issue(task_ref="tenant_a:task_1")
    with pytest.raises(ValueError):
        issue_correlation_token(
            tenant_id="t", key_id="k1", secret=KEY, now=datetime(2026, 1, 1)  # naive
        )


def test_extract_from_free_text_is_bounded_and_deduplicated() -> None:
    a, b = _issue().token, _issue().token
    body = f"Implements the feature.\n\naether: {a}\nrelated {b} and again {a}"
    assert extract_correlation_tokens(body) == (a, b)
    assert extract_correlation_tokens("") == ()
    many = " ".join(_issue().token for _ in range(20))
    assert len(extract_correlation_tokens(many)) == 8


def test_verifier_adapter() -> None:
    issued = _issue()
    verify = token_verifier(KEYS, now=NOW)
    assert verify(issued.token, "tenant_a") == issued.task_ref
    assert verify(issued.token, "tenant_b") is None
