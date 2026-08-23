"""Tests for ADR-008 D7 verification/faithfulness models (fail-closed)."""
from __future__ import annotations

import traceback
from datetime import datetime

import pytest
from pydantic import ValidationError

from services.model_runtime.verification.models import (
    VERIFICATION_SECRET_MARKERS,
    CitationCheck,
    ClaimStatement,
    VerificationRequest,
    VerificationResult,
    VerificationUnsafe,
)


def _raises(exc_type, fn, *args, **kwargs):
    """Assert that ``fn(*args, **kwargs)`` raises ``exc_type``."""
    try:
        fn(*args, **kwargs)
    except exc_type:
        return
    except Exception as exc:  # diagnostic only
        raise AssertionError(
            f"expected {exc_type.__name__}, got {type(exc).__name__}: {exc}"
        ) from exc
    raise AssertionError(f"expected {exc_type.__name__}, got no exception")


# ---------------------------------------------------------------------------
# ClaimStatement
# ---------------------------------------------------------------------------


def test_claim_statement_is_frozen_and_forbids_extra():
    claim = ClaimStatement(text="Revenue grew 12% in Q3.")
    with pytest.raises(ValidationError):
        claim.text = "mutated"
    with pytest.raises(ValidationError):
        ClaimStatement(text="ok", bogus=1)


def test_secret_markers_on_claim_text_raise_verification_unsafe():
    for marker in ("sk-live-abc123", "AKIAIOSFODNN7EXAMPLE", "eyJhbGciOiJIUzI1NiJ9"):
        _raises(VerificationUnsafe, ClaimStatement, text=f"the value {marker} leaked")


def test_secret_marker_check_is_case_insensitive():
    _raises(VerificationUnsafe, ClaimStatement, text="api key Sk-1234")
    _raises(VerificationUnsafe, ClaimStatement, text="access key akiaEXAMPLE")
    _raises(VerificationUnsafe, ClaimStatement, text="authorization: Bearer xyz")


def test_secret_marker_error_never_embeds_rejected_value():
    # Security guard: the raised VerificationUnsafe reports only the matched
    # marker, never the full rejected value. If the value were embedded
    # verbatim, traceback / exc_info logging would print the raw credential
    # the guard is meant to contain (the value survives as __cause__ on any
    # wrapper, so the rendered chain must stay value-free too).
    secret = "sk-live-ABC123secret"
    try:
        ClaimStatement(text=f"the value {secret} leaked")
    except VerificationUnsafe as err:
        rendered = "".join(
            traceback.format_exception(type(err), err, err.__traceback__)
        )
        assert secret not in str(err)
        assert secret not in repr(err)
        assert secret not in rendered
        # The matched marker is still reported (operators see WHICH pattern
        # tripped) — but the credential after it never is.
        assert "sk-" in str(err)
        assert "sk-live" not in str(err)
    else:  # pragma: no cover - test integrity
        raise AssertionError("expected VerificationUnsafe to be raised")


def test_secret_marker_error_hides_value_for_assignment_markers():
    # Assignment-style markers ("password=" / "secret=" / "key=") are unique
    # to the verification guard, so the credential after the "=" must never
    # surface in the exception chain for claim OR citation text.
    secret = "s3cretValu3"
    try:
        CitationCheck(
            reference_id="ref-1",
            claim_text=f"password={secret}",
            supported=True,
            method="token-overlap",
        )
    except VerificationUnsafe as err:
        rendered = "".join(
            traceback.format_exception(type(err), err, err.__traceback__)
        )
        assert secret not in str(err)
        assert secret not in rendered
        assert "password=" in str(err)  # marker reported, payload hidden
    else:  # pragma: no cover - test integrity
        raise AssertionError("expected VerificationUnsafe to be raised")


def test_claim_text_plain_marker_substring_is_not_enough():
    # "key=" marker requires an exact casefolded match, but ordinary prose that
    # merely contains a letter sequence is fine.
    claim = ClaimStatement(text="Keep your private keys safe.")
    assert claim.text == "Keep your private keys safe."


def test_empty_claim_text_raises_validation_error():
    with pytest.raises(ValidationError):
        ClaimStatement(text="")
    with pytest.raises(ValidationError):
        ClaimStatement(text="   ")


def test_claim_evidence_refs_default_to_empty_tuple():
    claim = ClaimStatement(text="Grounding claim.")
    assert claim.evidence_refs == ()


def test_claim_evidence_refs_accepted_as_tuple():
    claim = ClaimStatement(text="Grounding claim.", evidence_refs=("ref-1", "ref-2"))
    assert claim.evidence_refs == ("ref-1", "ref-2")


# ---------------------------------------------------------------------------
# CitationCheck
# ---------------------------------------------------------------------------


def test_citation_check_fields():
    check = CitationCheck(
        reference_id="ref-1",
        claim_text="Revenue grew 12% in Q3.",
        supported=True,
        method="token-overlap",
    )
    assert check.reference_id == "ref-1"
    assert check.claim_text == "Revenue grew 12% in Q3."
    assert check.supported is True
    assert check.method == "token-overlap"


def test_citation_check_rejects_secret_markers_in_claim_text():
    _raises(
        VerificationUnsafe,
        CitationCheck,
        reference_id="ref-1",
        claim_text="password=supersecret",
        supported=True,
        method="token-overlap",
    )


def test_citation_check_is_frozen_and_forbids_extra():
    check = CitationCheck(
        reference_id="ref-1", claim_text="ok", supported=False, method="exact"
    )
    with pytest.raises(ValidationError):
        check.supported = True
    with pytest.raises(ValidationError):
        CitationCheck(reference_id="ref-1", claim_text="ok", supported=False, bogus=1)


# ---------------------------------------------------------------------------
# VerificationRequest
# ---------------------------------------------------------------------------


def test_verification_request_allows_result_none():
    req = VerificationRequest(request_id="req-1")
    assert req.result is None
    explicit = VerificationRequest(request_id="req-1", result=None)
    assert explicit.result is None


def test_verification_request_is_frozen_and_forbids_extra():
    req = VerificationRequest(request_id="req-1")
    with pytest.raises(ValidationError):
        req.request_id = "req-2"
    with pytest.raises(ValidationError):
        VerificationRequest(request_id="req-1", bogus=1)


def test_verification_request_accepts_synthesis_result_when_present():
    synthesis = pytest.importorskip("services.model_runtime.synthesis.models")
    result = synthesis.SynthesisResult(
        request_id="req-1",
        plan_kind="grounded",
        content="Revenue grew 12% in Q3.",
        citations=(
            synthesis.EvidenceCitation(
                reference_id="ref-1",
                source="ledger",
                tenant_id="t-1",
                excerpt="Revenue grew 12% in Q3.",
            ),
        ),
        created_at=datetime(2026, 8, 8, 12, 0, 0),
    )
    req = VerificationRequest(request_id="req-1", result=result)
    assert req.result is result


# ---------------------------------------------------------------------------
# VerificationResult
# ---------------------------------------------------------------------------


def test_verification_result_carries_claims_and_checks():
    claim = ClaimStatement(text="Revenue grew 12% in Q3.", evidence_refs=("ref-1",))
    check = CitationCheck(
        reference_id="ref-1",
        claim_text=claim.text,
        supported=True,
        method="token-overlap",
    )
    result = VerificationResult(
        request_id="req-1",
        claims=(claim,),
        checks=(check,),
        faithful=True,
        leak_detected=False,
    )
    assert result.claims == (claim,)
    assert result.checks == (check,)


def test_verification_result_faithful_and_leak_defaults():
    result = VerificationResult(request_id="req-1", claims=(), checks=())
    # D7 fail-closed: faithful defaults to False until verification proves it.
    assert result.faithful is False
    assert result.leak_detected is False


def test_verification_result_faithful_leak_set_explicitly():
    result = VerificationResult(
        request_id="req-1",
        claims=(),
        checks=(),
        faithful=True,
        leak_detected=True,
    )
    assert result.faithful is True
    assert result.leak_detected is True


def test_verification_result_created_at_defaults_to_datetime():
    result = VerificationResult(request_id="req-1", claims=(), checks=())
    assert isinstance(result.created_at, datetime)
    assert result.created_at.tzinfo is not None


def test_verification_result_is_frozen_and_forbids_extra():
    result = VerificationResult(request_id="req-1", claims=(), checks=())
    with pytest.raises(ValidationError):
        result.claims = ()
    with pytest.raises(ValidationError):
        VerificationResult(request_id="req-1", claims=(), checks=(), bogus=True)
