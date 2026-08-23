"""VerificationService facade + barrel tests (ADR-008 D7 — Agent F).

Covers the public facade and package barrel for the verification/faithfulness
layer: ``verify`` returns a faithful result on clean supported content and a
``faithful=False`` result on an unsupported claim (no raise); ``enforce``
raises :class:`VerificationServiceError` on unfaithful or leaking content and
returns the result on faithful content; leak-detected content (built via
``model_construct`` to bypass the synthesis content guard) is reported, never
echoed; and the barrel re-exports the full public API.

Plain asserts only: ``_raises`` is the single tiny helper. ``pytest.importorskip``
guards ``synthesis.models`` while Commit 9 is still landing — the verification
package depends on it through ``verifier.py``.
"""

from __future__ import annotations

import traceback
from datetime import datetime, timezone

import pytest

# Commit 9 lands synthesis/models.py; skip this whole suite while that import
# surface is momentarily unavailable (verifier.py imports it eagerly).
synthesis_models = pytest.importorskip("services.model_runtime.synthesis.models")

import services.model_runtime.verification as verification_module
from services.model_runtime.verification import (
    VerificationService,
    VerificationServiceError,
)
from services.model_runtime.verification.models import VerificationResult

SynthesisResult = synthesis_models.SynthesisResult
EvidenceCitation = synthesis_models.EvidenceCitation

_NOW = datetime.now(timezone.utc)

# The exact public-API spec for the barrel (ADR-008 D7 commit brief).
_EXPECTED_ALL = [
    "VerificationUnsafe",
    "VERIFICATION_SECRET_MARKERS",
    "ClaimStatement",
    "CitationCheck",
    "VerificationRequest",
    "VerificationResult",
    "ClaimExtractionError",
    "MIN_CLAIM_CHARS",
    "ClaimExtractor",
    "FaithfulnessCheckError",
    "STOPWORDS",
    "FaithfulnessChecker",
    "VerificationFailure",
    "VerificationError",
    "VerificationEngine",
    "LEAK_MARKERS",
    "LeakHit",
    "SecretLeakDetector",
    "VerificationService",
    "VerificationServiceError",
]


def _citation(excerpt: str, reference_id: str = "r1") -> EvidenceCitation:
    return EvidenceCitation(
        reference_id=reference_id,
        source="aether.records.ledger.tx-1",
        tenant_id="tenant-a",
        excerpt=excerpt,
    )


def _result(
    content: str,
    citations: tuple[EvidenceCitation, ...] = (),
    request_id: str = "req-v1",
) -> SynthesisResult:
    return SynthesisResult(
        request_id=request_id,
        plan_kind="recursive",
        content=content,
        citations=citations,
        created_at=_NOW,
    )


def _leaky_result(content: str) -> SynthesisResult:
    # model_construct bypasses the synthesis content validator so a secret
    # marker can be placed in content for the leak-detection paths.
    return SynthesisResult.model_construct(
        request_id="req-leak",
        plan_kind="recursive",
        content=content,
        citations=(),
        created_at=_NOW,
    )


def _raises(exc_type: type[Exception], func) -> None:
    """Assert that calling func() raises exc_type (no pytest imports needed)."""
    try:
        func()
    except exc_type:
        return
    except Exception as err:
        raise AssertionError(
            f"expected {exc_type.__name__} but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


def test_verify_returns_faithful_result_on_clean_supported_content():
    service = VerificationService()
    result = _result(
        content="Revenue grew strongly last quarter [ref:r1].",
        citations=(_citation(excerpt="The company revenue grew strongly in the last quarter."),),
    )

    vresult = service.verify(result)

    assert isinstance(vresult, VerificationResult)
    assert vresult.request_id == "req-v1"
    assert vresult.faithful is True
    assert vresult.leak_detected is False
    assert len(vresult.claims) == 1
    assert vresult.claims[0].text == "Revenue grew strongly last quarter [ref:r1]."
    assert len(vresult.checks) == 1
    assert vresult.checks[0].supported is True
    assert vresult.checks[0].reference_id == "r1"


def test_verify_returns_faithful_false_on_unsupported_claim_no_raise():
    service = VerificationService()
    result = _result(
        content="Revenue grew strongly last quarter.",
        citations=(_citation(excerpt="The board approved a dividend payout."),),
    )

    vresult = service.verify(result)

    assert isinstance(vresult, VerificationResult)
    assert vresult.faithful is False
    assert vresult.leak_detected is False
    assert len(vresult.checks) == 1
    assert vresult.checks[0].supported is False


def test_enforce_raises_service_error_on_unfaithful():
    service = VerificationService()
    result = _result(
        content="Revenue grew strongly last quarter.",
        citations=(_citation(excerpt="The board approved a dividend payout."),),
    )

    _raises(VerificationServiceError, lambda: service.enforce(result))


def test_enforce_returns_result_on_faithful_content():
    service = VerificationService()
    result = _result(
        content="Revenue grew strongly last quarter [ref:r1].",
        citations=(_citation(excerpt="The company revenue grew strongly in the last quarter."),),
    )

    vresult = service.enforce(result)

    assert isinstance(vresult, VerificationResult)
    assert vresult.faithful is True
    assert vresult.request_id == "req-v1"


def test_verify_reports_leak_detected_on_leaked_content():
    service = VerificationService()
    result = _leaky_result("Revenue grew strongly last quarter.\n# api key sk-live-1234")

    vresult = service.verify(result)

    assert isinstance(vresult, VerificationResult)
    assert vresult.leak_detected is True
    assert vresult.faithful is False


def test_enforce_raises_service_error_on_leaked_content():
    service = VerificationService()
    result = _leaky_result("Revenue grew strongly last quarter.\n# api key sk-live-1234")

    _raises(VerificationServiceError, lambda: service.enforce(result))


def test_secret_violation_error_message_contains_no_sk():
    service = VerificationService()
    result = _leaky_result("The deployment key sk-live-42 must rotate.")

    try:
        service.verify(result)
        raise AssertionError("expected VerificationServiceError to be raised")
    except VerificationServiceError as err:
        assert "sk-" not in str(err)
        assert "sk-live-42" not in str(err)


def test_secret_violation_chain_never_echoes_rejected_credential():
    # The VerificationUnsafe raised when an extracted claim trips the guard is
    # retained as __cause__ on the VerificationServiceError. The wrapper's own
    # message is already content-free; this regression test pins that the WHOLE
    # exception chain — everything traceback / exc_info logging renders — stays
    # free of the rejected credential.
    secret = "s3cretValue42"
    service = VerificationService()
    # "password=" is a verification marker but NOT a synthesis content marker,
    # so a real SynthesisResult carries it past the synthesis guard and the
    # verification guard rejects it during claim extraction (no model_construct
    # needed here).
    result = _result(content=f"The deployment password={secret} must rotate.")

    try:
        service.verify(result)
        raise AssertionError("expected VerificationServiceError to be raised")
    except VerificationServiceError as err:
        rendered = "".join(
            traceback.format_exception(type(err), err, err.__traceback__)
        )
        assert secret not in rendered
        # Walk __cause__ explicitly: format_exception folds it into the chain,
        # but asserting both surfaces catches a regression in either.
        node = err
        seen: set[int] = set()
        while node is not None and id(node) not in seen:
            seen.add(id(node))
            assert secret not in str(node)
            assert secret not in repr(node)
            node = node.__cause__


def test_barrel_all_matches_spec():
    assert verification_module.__all__ == _EXPECTED_ALL


def test_barrel_exports_every_public_name():
    for name in _EXPECTED_ALL:
        assert hasattr(verification_module, name), name
        assert getattr(verification_module, name) is not None
