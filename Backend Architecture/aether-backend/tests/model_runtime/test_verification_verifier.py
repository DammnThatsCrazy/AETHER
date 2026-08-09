"""Fail-closed verification engine tests (ADR-008 D7, Commit 10-D).

Plain asserts only: no ``pytest.raises``, no fixture/mock libraries.
``_raises`` is the single tiny helper, so this suite runs identically under the
minimal test runtime used by some CI environments.

Concurrency / gating: the sibling ``verification/models.py`` (Commit 10-A) and
``synthesis/models.py`` (Commit 9) land in parallel commit efforts. Both are
importor-skipped so this suite passes (as a skip) until they are importable;
once they are, the whole suite runs against the real contracts.

Coverage: the D7 fail-closed gate. ``run``/``enforce`` semantics, the
empty-claims edge (``all([])`` is ``True`` so ``faithful`` then depends only on
``leak_detected``), and leak detection over content AND citation excerpts.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("services.model_runtime.synthesis.models")
pytest.importorskip("services.model_runtime.verification.models")

import services.model_runtime.verification.verifier as verifier_module  # noqa: E402 - after importorskip guards
from services.model_runtime.synthesis.models import (  # noqa: E402
    EvidenceCitation,
    SynthesisResult,
)
from services.model_runtime.verification.claims import (  # noqa: E402
    ClaimExtractionError,
)
from services.model_runtime.verification.leaks import SecretLeakDetector  # noqa: E402
from services.model_runtime.verification.models import (  # noqa: E402
    ClaimStatement,
    CitationCheck,
)
from services.model_runtime.verification.verifier import (  # noqa: E402
    VerificationEngine,
    VerificationError,
    VerificationFailure,
)

_NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)


def _raises(exc_type, func):
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


# ---------------------------------------------------------------------------
# Helpers — real contract types plus deterministic fakes for the engine stages
# ---------------------------------------------------------------------------


def _claim(text="Revenue grew 12% in Q3."):
    return ClaimStatement(text=text)


def _check(supported=True, reference_id="ref-1", claim_text="Revenue grew 12% in Q3."):
    return CitationCheck(
        reference_id=reference_id,
        claim_text=claim_text,
        supported=supported,
        method="token-overlap",
    )


def _citation(excerpt="Revenue grew 12% in Q3."):
    return EvidenceCitation(
        reference_id="ref-1",
        source="aether.records.ledger.tx-1",
        tenant_id="t-1",
        excerpt=excerpt,
    )


def _result(content="Revenue grew 12% in Q3.", citations=()):
    return SynthesisResult(
        request_id="req-1",
        plan_kind="recursive",
        content=content,
        citations=citations,
        created_at=_NOW,
    )


def _leaky_result(content):
    """SynthesisResult carrying a credential marker, built without validation.

    ``model_construct`` bypasses pydantic validation so the secret-shaped
    content reaches the leak sweep the way a buggy/malicious synthesis stage
    could produce it.
    """
    return SynthesisResult.model_construct(
        request_id="req-1",
        plan_kind="recursive",
        content=content,
        citations=(),
        created_at=_NOW,
    )


class _FakeExtractor:
    """Returns a fixed claim list, or raises a configured error."""

    def __init__(self, claims=(), error=None):
        self._claims = list(claims)
        self._error = error

    def extract(self, content):
        if self._error is not None:
            raise self._error
        return list(self._claims)


class _FakeChecker:
    """Returns a fixed citation-check list regardless of inputs."""

    def __init__(self, checks=()):
        self._checks = list(checks)

    def check(self, claims, citations):
        return list(self._checks)


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


def test_module_exports_exact():
    assert verifier_module.__all__ == [
        "VerificationFailure",
        "VerificationError",
        "VerificationEngine",
    ]
    for name in verifier_module.__all__:
        assert hasattr(verifier_module, name), name


def test_exception_hierarchy():
    assert issubclass(VerificationFailure, Exception)
    assert issubclass(VerificationError, Exception)
    assert VerificationFailure is not VerificationError


def test_default_engine_resolves_all_siblings():
    # Default construction resolves the real extractor, checker, and leak
    # detector via the lazy imports (claims.py, faithfulness.py, leaks.py).
    engine = VerificationEngine()
    assert engine._extractor is not None  # noqa: SLF001 - construction probe
    assert engine._checker is not None  # noqa: SLF001 - construction probe
    assert engine._leaks is not None  # noqa: SLF001 - construction probe


# ---------------------------------------------------------------------------
# run() — faithfulness disposition
# ---------------------------------------------------------------------------


def test_fully_supported_content_is_faithful():
    engine = VerificationEngine(
        extractor=_FakeExtractor(claims=[_claim()]),
        checker=_FakeChecker(checks=[_check(supported=True)]),
        leaks=SecretLeakDetector(),
    )
    vresult = engine.run(_result())
    assert vresult.request_id == "req-1"
    assert vresult.claims == (_claim(),)
    assert vresult.checks == (_check(supported=True),)
    assert vresult.faithful is True
    assert vresult.leak_detected is False
    assert vresult.created_at.tzinfo is not None


def test_single_unsupported_claim_marks_unfaithful():
    engine = VerificationEngine(
        extractor=_FakeExtractor(
            claims=[_claim(text="First claim stands."), _claim(text="Second claim.")]
        ),
        checker=_FakeChecker(
            checks=[_check(supported=True), _check(supported=False)]
        ),
        leaks=SecretLeakDetector(),
    )
    vresult = engine.run(_result())
    assert len(vresult.checks) == 2
    assert vresult.faithful is False
    assert vresult.leak_detected is False


def test_default_engine_full_pipeline_is_faithful():
    # Integration path: real extractor + real faithfulness checker + real leak
    # detector over matching content/citations.
    content = "Gold reserves increased."
    citations = (_citation(excerpt="Gold reserves increased markedly."),)
    vresult = VerificationEngine().run(_result(content=content, citations=citations))
    assert vresult.claims == (_claim(text="Gold reserves increased."),)
    assert vresult.checks[0].supported is True
    assert vresult.faithful is True
    assert vresult.leak_detected is False


def test_integration_unsupported_claim_is_unfaithful():
    # Real pipeline, but the only citation does not support the claim. "reserves"
    # must not appear in the excerpt or the token-overlap check would support it.
    content = "Gold reserves increased."
    citations = (_citation(excerpt="Marketing spend declined sharply."),)
    vresult = VerificationEngine().run(_result(content=content, citations=citations))
    assert vresult.checks[0].supported is False
    assert vresult.faithful is False


# ---------------------------------------------------------------------------
# run() — leak detection (content AND citation excerpts)
# ---------------------------------------------------------------------------


def test_leak_in_content_is_detected():
    engine = VerificationEngine(
        extractor=_FakeExtractor(claims=[_claim()]),
        checker=_FakeChecker(checks=[_check(supported=True)]),
        leaks=SecretLeakDetector(),
    )
    vresult = engine.run(_leaky_result("the token sk-live-12345 leaked here"))
    assert vresult.leak_detected is True
    assert vresult.faithful is False


def test_leak_in_citation_excerpt_is_detected():
    engine = VerificationEngine(
        extractor=_FakeExtractor(claims=[_claim()]),
        checker=_FakeChecker(checks=[_check(supported=True)]),
        leaks=SecretLeakDetector(),
    )
    citation = EvidenceCitation.model_construct(
        reference_id="ref-1",
        source="aether.records.ledger.tx-1",
        tenant_id="t-1",
        excerpt="the header Authorization: Bearer abc leaked",
    )
    vresult = engine.run(_result(citations=(citation,)))
    assert vresult.leak_detected is True
    assert vresult.faithful is False


def test_clean_content_and_citations_no_leak():
    engine = VerificationEngine(
        extractor=_FakeExtractor(claims=[_claim()]),
        checker=_FakeChecker(checks=[_check(supported=True)]),
        leaks=SecretLeakDetector(),
    )
    vresult = engine.run(_result(citations=(_citation(),)))
    assert vresult.leak_detected is False


# ---------------------------------------------------------------------------
# Empty-claims edge: all([]) is True, so faithful depends only on leak_detected
# ---------------------------------------------------------------------------


def test_empty_claims_clean_is_faithful():
    engine = VerificationEngine(
        extractor=_FakeExtractor(claims=[]),
        checker=_FakeChecker(checks=[]),
        leaks=SecretLeakDetector(),
    )
    vresult = engine.run(_result())
    assert vresult.claims == ()
    assert vresult.checks == ()
    # all() over zero checks is True, and no leak is present, so faithful=True.
    assert vresult.faithful is True
    assert vresult.leak_detected is False


def test_empty_claims_with_leak_is_unfaithful():
    engine = VerificationEngine(
        extractor=_FakeExtractor(claims=[]),
        checker=_FakeChecker(checks=[]),
        leaks=SecretLeakDetector(),
    )
    vresult = engine.run(_leaky_result("sk-leaked despite zero claims"))
    # all([]) is True, but faithful is gated by the leak detector: faithful is
    # NOT independently true when a credential marker is present.
    assert vresult.claims == ()
    assert vresult.checks == ()
    assert vresult.leak_detected is True
    assert vresult.faithful is False
    assert vresult.faithful is (not vresult.leak_detected)


# ---------------------------------------------------------------------------
# run() — verification cannot complete (fail-closed)
# ---------------------------------------------------------------------------


def test_run_raises_verification_error_when_extractor_raises():
    engine = VerificationEngine(
        extractor=_FakeExtractor(error=ClaimExtractionError("unparseable")),
        checker=_FakeChecker(checks=[]),
        leaks=SecretLeakDetector(),
    )
    _raises(VerificationError, lambda: engine.run(_result()))


# ---------------------------------------------------------------------------
# enforce() — the fail-closed gate
# ---------------------------------------------------------------------------


def test_enforce_returns_result_when_faithful():
    engine = VerificationEngine(
        extractor=_FakeExtractor(claims=[_claim()]),
        checker=_FakeChecker(checks=[_check(supported=True)]),
        leaks=SecretLeakDetector(),
    )
    vresult = engine.enforce(_result())
    assert vresult.faithful is True
    assert vresult.leak_detected is False


def test_enforce_raises_on_unsupported_claim():
    engine = VerificationEngine(
        extractor=_FakeExtractor(claims=[_claim()]),
        checker=_FakeChecker(checks=[_check(supported=False)]),
        leaks=SecretLeakDetector(),
    )
    _raises(VerificationFailure, lambda: engine.enforce(_result()))


def test_enforce_raises_on_leak():
    engine = VerificationEngine(
        extractor=_FakeExtractor(claims=[_claim()]),
        checker=_FakeChecker(checks=[_check(supported=True)]),
        leaks=SecretLeakDetector(),
    )
    _raises(VerificationFailure, lambda: engine.enforce(_leaky_result("sk-leaked")))
