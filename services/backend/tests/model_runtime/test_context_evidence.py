"""Grounded-synthesis context data-model tests (ADR-008 D6).

Plain asserts only: no pytest.raises, no fixture/mock libraries. ``_raises`` is
the single tiny helper, so this suite runs identically under the minimal test
runtime used by some CI environments.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError

import services.model_runtime.context.evidence as evidence_module
from services.model_runtime.context.evidence import (
    ContextBundle,
    EvidenceBounds,
    EvidenceBudget,
    EvidenceItem,
    EvidenceSet,
    EvidenceUnsafe,
)

_NOW = datetime.now(timezone.utc)

_SECRET_MARKERS = (
    "sk-",
    "AKIA",
    "Bearer ",
    "-----BEGIN",
    "Authorization:",
    "X-Api-Key:",
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


def _item(content="plain evidence", source="aether.records.ledger.tx-1", reference_id="r1"):
    return EvidenceItem(
        reference_id=reference_id,
        source=source,
        tenant_id="t1",
        content=content,
        collected_at=_NOW,
    )


def _set(query="plain query", items=()):
    return EvidenceSet(
        tenant_id="t1",
        profile_id="p1",
        query=query,
        items=items,
        created_at=_NOW,
    )


def _bundle(query="plain query", synthesis_instructions=""):
    return ContextBundle(
        tenant_id="t1",
        profile_id="p1",
        query=query,
        evidence=_set(query=query),
        synthesis_instructions=synthesis_instructions,
        created_at=_NOW,
    )


def test_evidence_item_defaults():
    item = _item()
    assert item.reference_id == "r1"
    assert item.source == "aether.records.ledger.tx-1"
    assert item.tenant_id == "t1"
    assert item.content == "plain evidence"
    assert item.collected_at == _NOW
    assert item.metadata == {}


def test_evidence_item_is_frozen():
    item = _item()
    _raises(ValidationError, lambda: setattr(item, "source", "changed"))
    _raises(ValidationError, lambda: setattr(item, "content", "changed"))
    _raises(ValidationError, lambda: setattr(item, "metadata", {"k": "v"}))


def test_evidence_item_forbids_unknown_fields():
    _raises(
        ValidationError,
        lambda: EvidenceItem(
            reference_id="r",
            source="s",
            tenant_id="t",
            content="c",
            collected_at=_NOW,
            bogus=1,
        ),
    )


def test_evidence_set_forbids_unknown_fields():
    _raises(
        ValidationError,
        lambda: EvidenceSet(tenant_id="t", profile_id="p", query="q", created_at=_NOW, bogus=1),
    )


def test_context_bundle_forbids_unknown_fields():
    _raises(
        ValidationError,
        lambda: ContextBundle(
            tenant_id="t", profile_id="p", query="q", evidence=_set(), created_at=_NOW, bogus=1
        ),
    )


def test_content_rejects_all_secret_markers():
    for marker in _SECRET_MARKERS:
        _raises(EvidenceUnsafe, lambda marker=marker: _item(content=f"note {marker} tail"))


def test_source_rejects_all_secret_markers():
    for marker in _SECRET_MARKERS:
        _raises(EvidenceUnsafe, lambda marker=marker: _item(source=f"aether.{marker}id"))


def test_bundle_query_rejects_all_secret_markers():
    for marker in _SECRET_MARKERS:
        _raises(EvidenceUnsafe, lambda marker=marker: _bundle(query=f"what is {marker}"))


def test_synthesis_instructions_reject_all_secret_markers():
    for marker in _SECRET_MARKERS:
        _raises(
            EvidenceUnsafe,
            lambda marker=marker: _bundle(synthesis_instructions=f"echo {marker} here"),
        )


def test_secret_markers_are_case_insensitive():
    _raises(EvidenceUnsafe, lambda: _item(content="MY KEY BEGINS SK-12345"))
    _raises(EvidenceUnsafe, lambda: _item(content="pem block -----BEGIN CERTIFICATE-----"))
    _raises(EvidenceUnsafe, lambda: _item(source="aether.Bearer token"))
    _raises(EvidenceUnsafe, lambda: _bundle(query="authorization: foo"))
    _raises(EvidenceUnsafe, lambda: _bundle(synthesis_instructions="x-api-key: secret"))


def test_evidence_set_rejects_more_than_max_items():
    items = tuple(_item(reference_id=f"r{i}") for i in range(65))
    _raises(EvidenceBounds, lambda: _set(items=items))


def test_evidence_set_allows_exactly_max_items():
    items = tuple(_item(reference_id=f"r{i}") for i in range(64))
    es = _set(items=items)
    assert len(es.items) == 64


def test_evidence_set_rejects_oversized_content():
    long_item = _item(content="x" * 4097)
    _raises(EvidenceBounds, lambda: _set(items=(long_item,)))


def test_evidence_set_allows_max_content_chars():
    ok_item = _item(content="x" * 4096)
    es = _set(items=(ok_item,))
    assert len(es.items[0].content) == 4096


def test_empty_evidence_set_ok():
    es = _set()
    assert es.items == ()


def test_evidence_budget_defaults():
    budget = EvidenceBudget()
    assert budget.max_items == 64
    assert budget.max_content_chars == 4096
    assert budget.freshness_seconds == 300


def test_evidence_budget_rejects_non_positive():
    _raises(EvidenceBounds, lambda: EvidenceBudget(max_items=0))
    _raises(EvidenceBounds, lambda: EvidenceBudget(max_items=-1))
    _raises(EvidenceBounds, lambda: EvidenceBudget(max_content_chars=0))
    _raises(EvidenceBounds, lambda: EvidenceBudget(max_content_chars=-4096))
    _raises(EvidenceBounds, lambda: EvidenceBudget(freshness_seconds=0))
    _raises(EvidenceBounds, lambda: EvidenceBudget(freshness_seconds=-300))


def test_evidence_budget_is_frozen():
    budget = EvidenceBudget()
    _raises(ValidationError, lambda: setattr(budget, "max_items", 10))


def test_evidence_budget_forbids_unknown_fields():
    _raises(ValidationError, lambda: EvidenceBudget(bogus=1))


def test_context_bundle_wraps_evidence_set():
    es = _set(items=(_item(),))
    bundle = ContextBundle(
        tenant_id="t1",
        profile_id="p1",
        query="plain query",
        evidence=es,
        created_at=_NOW,
    )
    assert bundle.evidence == es
    assert bundle.evidence.items == es.items
    assert bundle.tenant_id == "t1"
    assert bundle.profile_id == "p1"
    assert bundle.query == "plain query"
    assert bundle.synthesis_instructions == ""
    assert bundle.created_at == _NOW


def test_evidence_module_exports_complete():
    expected = {
        "ContextBundle",
        "EvidenceBounds",
        "EvidenceBudget",
        "EvidenceItem",
        "EvidenceSet",
        "EvidenceUnsafe",
    }
    assert set(evidence_module.__all__) == expected
    for name in expected:
        assert hasattr(evidence_module, name), name
