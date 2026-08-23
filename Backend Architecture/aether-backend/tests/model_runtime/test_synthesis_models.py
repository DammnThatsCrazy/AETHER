"""Grounded-synthesis data-model tests (ADR-008 D6).

Plain asserts only: no pytest.raises, no fixture/mock libraries. ``_raises`` is
the single tiny helper, so this suite runs identically under the minimal test
runtime used by some CI environments.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError

import services.model_runtime.synthesis.models as synthesis_module
from services.model_runtime.context.evidence import EvidenceSet
from services.model_runtime.synthesis.models import (
    EvidenceCitation,
    SYNTHESIS_SECRET_MARKERS,
    SynthesisRequest,
    SynthesisResult,
    SynthesisUnsafe,
)

_NOW = datetime.now(timezone.utc)

_SECRET_MARKERS = (
    "sk-",
    "AKIA",
    "Bearer ",
    "-----BEGIN",
    "Authorization:",
    "X-Api-Key:",
    "eyJ",
)


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


def _citation(excerpt="plain excerpt", reference_id="r1"):
    return EvidenceCitation(
        reference_id=reference_id,
        source="aether.records.ledger.tx-1",
        tenant_id="t1",
        excerpt=excerpt,
    )


def _evidence_set():
    return EvidenceSet(
        tenant_id="t1",
        profile_id="p1",
        query="plain query",
        items=(),
        created_at=_NOW,
    )


def _request(query="plain query", evidence=None):
    return SynthesisRequest(
        tenant_id="t1",
        profile_id="p1",
        query=query,
        plan_kind="recursive",
        evidence=evidence,
    )


def _result(content="plain grounded content", citations=()):
    return SynthesisResult(
        request_id="req-1",
        plan_kind="recursive",
        content=content,
        citations=citations,
        created_at=_NOW,
    )


def test_secret_markers_constant_exported():
    assert SYNTHESIS_SECRET_MARKERS == _SECRET_MARKERS
    assert isinstance(SYNTHESIS_SECRET_MARKERS, tuple)


def test_citation_defaults_and_values():
    citation = _citation()
    assert citation.reference_id == "r1"
    assert citation.source == "aether.records.ledger.tx-1"
    assert citation.tenant_id == "t1"
    assert citation.excerpt == "plain excerpt"


def test_citation_is_frozen():
    citation = _citation()
    _raises(ValidationError, lambda: setattr(citation, "excerpt", "changed"))
    _raises(ValidationError, lambda: setattr(citation, "reference_id", "changed"))


def test_citation_forbids_unknown_fields():
    _raises(
        ValidationError,
        lambda: EvidenceCitation(reference_id="r", source="s", tenant_id="t", excerpt="e", bogus=1),
    )


def test_excerpt_rejects_all_secret_markers():
    for marker in _SECRET_MARKERS:
        _raises(SynthesisUnsafe, lambda marker=marker: _citation(excerpt=f"note {marker} tail"))


def test_content_rejects_all_secret_markers():
    for marker in _SECRET_MARKERS:
        _raises(SynthesisUnsafe, lambda marker=marker: _result(content=f"note {marker} tail"))


def test_query_rejects_all_secret_markers():
    for marker in _SECRET_MARKERS:
        _raises(SynthesisUnsafe, lambda marker=marker: _request(query=f"what is {marker}"))


def test_secret_markers_are_case_insensitive():
    _raises(SynthesisUnsafe, lambda: _result(content="MY KEY BEGINS SK-12345"))
    _raises(SynthesisUnsafe, lambda: _citation(excerpt="pem block -----BEGIN CERTIFICATE-----"))
    _raises(SynthesisUnsafe, lambda: _request(query="authorization: foo"))
    _raises(SynthesisUnsafe, lambda: _result(content="header x-api-key: secret"))
    _raises(SynthesisUnsafe, lambda: _request(query="token eyjhbGciOiJIUzI1NiJ9"))
    _raises(SynthesisUnsafe, lambda: _citation(excerpt="bearer TOKEN123"))


def test_benign_content_passes():
    result = _result(content="The ledger balance is $1,024.50 as of 2026-08-08.")
    assert "ledger" in result.content
    citation = _citation(excerpt="Transaction tx-1 settled successfully.")
    assert "settled" in citation.excerpt
    req = _request(query="What is the current ledger balance?")
    assert "ledger" in req.query


def test_request_default_created_at_is_auto_now():
    req = _request()
    assert isinstance(req.created_at, datetime)
    assert req.created_at.tzinfo is not None
    delta = abs((datetime.now(timezone.utc) - req.created_at).total_seconds())
    assert delta < 5


def test_request_accepts_explicit_created_at():
    req = SynthesisRequest(
        tenant_id="t1",
        profile_id="p1",
        query="plain query",
        plan_kind="recursive",
        created_at=_NOW,
    )
    assert req.created_at == _NOW


def test_request_defaults():
    req = _request()
    assert req.tenant_id == "t1"
    assert req.profile_id == "p1"
    assert req.query == "plain query"
    assert req.plan_kind == "recursive"
    assert req.evidence is None
    assert req.synthesis_instructions == ""


def test_request_evidence_none_allowed():
    req = _request(evidence=None)
    assert req.evidence is None


def test_request_accepts_evidence_set():
    req = _request(evidence=_evidence_set())
    assert req.evidence is not None
    assert req.evidence == _evidence_set()
    assert req.evidence.items == ()


def test_request_is_frozen():
    req = _request()
    _raises(ValidationError, lambda: setattr(req, "query", "changed"))
    _raises(ValidationError, lambda: setattr(req, "plan_kind", "changed"))


def test_request_forbids_unknown_fields():
    _raises(
        ValidationError,
        lambda: SynthesisRequest(
            tenant_id="t", profile_id="p", query="q", plan_kind="recursive", bogus=1
        ),
    )


def test_request_requires_core_fields():
    _raises(
        ValidationError,
        lambda: SynthesisRequest(tenant_id="t", profile_id="p", plan_kind="recursive"),
    )
    _raises(
        ValidationError,
        lambda: SynthesisRequest(tenant_id="t", profile_id="p", query="q"),
    )


def test_result_defaults_and_values():
    result = _result()
    assert result.request_id == "req-1"
    assert result.plan_kind == "recursive"
    assert result.content == "plain grounded content"
    assert result.citations == ()
    assert result.created_at == _NOW


def test_empty_citations_tuple_is_valid():
    result = _result(citations=())
    assert result.citations == ()


def test_result_accepts_citations():
    result = _result(citations=(_citation(), _citation(reference_id="r2", excerpt="second")))
    assert len(result.citations) == 2
    assert result.citations[0].reference_id == "r1"
    assert result.citations[1].reference_id == "r2"
    assert result.citations[1].excerpt == "second"


def test_result_is_frozen():
    result = _result()
    _raises(ValidationError, lambda: setattr(result, "content", "changed"))
    _raises(ValidationError, lambda: setattr(result, "citations", ()))


def test_result_forbids_unknown_fields():
    _raises(
        ValidationError,
        lambda: SynthesisResult(
            request_id="r", plan_kind="recursive", content="c", citations=(), bogus=1
        ),
    )


def test_result_requires_plan_kind_content_citations():
    _raises(
        ValidationError,
        lambda: SynthesisResult(request_id="r", content="c", citations=(), created_at=_NOW),
    )
    _raises(
        ValidationError,
        lambda: SynthesisResult(
            request_id="r", plan_kind="recursive", citations=(), created_at=_NOW
        ),
    )
    _raises(
        ValidationError,
        lambda: SynthesisResult(
            request_id="r", plan_kind="recursive", content="c", created_at=_NOW
        ),
    )


def test_synthesis_module_exports_complete():
    expected = {
        "EvidenceCitation",
        "SYNTHESIS_SECRET_MARKERS",
        "SynthesisRequest",
        "SynthesisResult",
        "SynthesisUnsafe",
    }
    assert set(synthesis_module.__all__) == expected
    for name in expected:
        assert hasattr(synthesis_module, name), name
