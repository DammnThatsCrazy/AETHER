"""Tests for the grounded-synthesis result renderer (ADR-008 D6, Agent E).

Covers the grounded markdown render (plan kind header, request id, content,
numbered ``[ref:...]`` citation lines), 160-char excerpt truncation, content
truncation via ``render_truncated``, the renderer's fail-closed credential scan
(defense-in-depth beyond sibling A's models field layer), the output size cap,
and determinism. Plain asserts only: no ``pytest.raises``, no fixture/mock
libraries — ``_raises`` is the single tiny helper.

Cross-commit note: sibling A's ``synthesis/models.py`` (same commit) may not
have landed — or may land with a different shape — when this suite is
collected. The model import is guarded: when the spec-exact names are not
importable the whole module skips rather than failing collection.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

try:  # Commit-9 sibling modules; skip the suite until the package lands cleanly
    import services.model_runtime.synthesis.renderer as renderer_module

    from services.model_runtime.synthesis.renderer import (
        DEFAULT_MAX_OUTPUT_CHARS,
        SynthesisRenderError,
        SynthesisRenderer,
    )
    from services.model_runtime.synthesis.models import (
        SYNTHESIS_SECRET_MARKERS,
        EvidenceCitation,
        SynthesisResult,
    )
except ImportError as exc:  # pragma: no cover - depends on concurrent siblings
    pytest.skip(
        "sibling synthesis package not fully landed yet; skipping renderer tests: "
        f"{exc}",
        allow_module_level=True,
    )

_NOW = datetime.now(timezone.utc)

# The full renderer credential-marker set: the first seven mirror sibling A's
# SYNTHESIS_SECRET_MARKERS; the "password=/secret=/key=" forms are renderer-only.
_RENDERER_MARKERS = (
    "sk-",
    "AKIA",
    "Bearer ",
    "-----BEGIN",
    "Authorization:",
    "X-Api-Key:",
    "eyJ",
    "password=",
    "secret=",
    "key=",
)


def _raises(exc_type, fn, *args, **kwargs):
    """Assert that ``fn(*args, **kwargs)`` raises ``exc_type``; return the error."""
    try:
        fn(*args, **kwargs)
    except exc_type as err:
        return err
    except Exception as err:  # diagnostic only
        raise AssertionError(
            f"expected {exc_type.__name__}, got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__}, nothing raised")


def _citation(
    excerpt="plain excerpt",
    *,
    reference_id="ledger-1",
    source="aether.records.ledger.tx-1",
):
    return EvidenceCitation(
        reference_id=reference_id,
        source=source,
        tenant_id="tenant-a",
        excerpt=excerpt,
    )


def _result(content="The ledger balance is $1,204.50 as of 2026-08-08.", citations=()):
    return SynthesisResult(
        request_id="req-123",
        plan_kind="recursive",
        content=content,
        citations=citations,
        created_at=_NOW,
    )


def _result_bypass(**overrides) -> SynthesisResult:
    """Build a result that slipped past the models field-layer secret validators.

    The models module raises ``SynthesisUnsafe`` for credential-shaped text at
    construction time, so to exercise the renderer's OWN credential guard we
    construct the model without validation via ``model_construct``.
    """
    defaults = {
        "request_id": "req-123",
        "plan_kind": "recursive",
        "content": "The ledger balance is $1,204.50 as of 2026-08-08.",
        "citations": (),
        "created_at": _NOW,
    }
    defaults.update(overrides)
    return SynthesisResult.model_construct(**defaults)


def _citation_bypass(excerpt, **overrides) -> EvidenceCitation:
    """Build a citation whose excerpt skipped the field-layer secret validators."""
    defaults = {
        "reference_id": "ledger-1",
        "source": "aether.records.ledger.tx-1",
        "tenant_id": "tenant-a",
        "excerpt": excerpt,
    }
    defaults.update(overrides)
    return EvidenceCitation.model_construct(**defaults)


def test_exports_and_default_cap():
    assert renderer_module.__all__ == [
        "SynthesisRenderError",
        "DEFAULT_MAX_OUTPUT_CHARS",
        "SynthesisRenderer",
    ]
    assert DEFAULT_MAX_OUTPUT_CHARS == 16000


def test_renderer_markers_cover_sibling_models_markers():
    assert set(renderer_module._RENDERER_SECRET_MARKERS).issuperset(SYNTHESIS_SECRET_MARKERS)
    assert set(_RENDERER_MARKERS) == set(renderer_module._RENDERER_SECRET_MARKERS)


def test_render_happy_path_numbers_citations_in_order():
    citations = (
        _citation("Closing balance is $1,204.50.", reference_id="ledger-1"),
        _citation("Twelve wires settled on 2026-08-08.", reference_id="treasury-2"),
        _citation("Threshold alert cleared.", reference_id="risk-3"),
    )
    output = SynthesisRenderer().render(_result(citations=citations))

    assert output.startswith("# recursive result")
    assert "request: req-123" in output
    assert "The ledger balance is $1,204.50 as of 2026-08-08." in output
    assert "## Evidence" in output
    assert (
        "1. [ref:ledger-1] (source: aether.records.ledger.tx-1) "
        "— Closing balance is $1,204.50." in output
    )
    assert "2. [ref:treasury-2]" in output
    assert "3. [ref:risk-3]" in output
    assert (
        output.index("1. [ref:ledger-1]")
        < output.index("2. [ref:treasury-2]")
        < output.index("3. [ref:risk-3]")
    )


def test_render_omits_evidence_section_when_no_citations():
    output = SynthesisRenderer().render(_result(citations=()))
    assert "## Evidence" not in output
    assert output.endswith("The ledger balance is $1,204.50 as of 2026-08-08.")


def test_render_truncates_long_excerpt_to_160_chars():
    long_excerpt = "x" * 200
    output = SynthesisRenderer().render(
        _result(citations=(_citation(long_excerpt, reference_id="r1"),))
    )
    assert "[ref:r1]" in output
    assert ("x" * 160) + "…" in output
    assert "x" * 161 not in output


def test_render_truncated_shortens_content_and_keeps_citations():
    content = "A" * 500
    citations = (_citation("balance confirmed", reference_id="ledger-1"),)
    output = SynthesisRenderer().render_truncated(
        _result(content=content, citations=citations), limit=100
    )

    assert output.startswith("# recursive result")
    assert "request: req-123" in output
    assert ("A" * 100) + "…" in output
    assert "A" * 101 not in output
    assert "1. [ref:ledger-1]" in output
    assert "balance confirmed" in output


def test_render_truncated_keeps_short_content_intact():
    content = "Short answer."
    citations = (_citation("excerpt ok", reference_id="r1"),)
    output = SynthesisRenderer().render_truncated(
        _result(content=content, citations=citations), limit=100
    )
    assert content in output
    assert "…" not in output


def test_render_rejects_secret_marker_in_content():
    renderer = SynthesisRenderer()
    for marker in _RENDERER_MARKERS:
        result = _result_bypass(content=f"note {marker} tail")
        _raises(SynthesisRenderError, renderer.render, result)


def test_render_rejects_secret_marker_in_excerpt():
    renderer = SynthesisRenderer()
    for marker in _RENDERER_MARKERS:
        citation = _citation_bypass(excerpt=f"note {marker} tail")
        result = _result_bypass(citations=(citation,))
        _raises(SynthesisRenderError, renderer.render, result)


def test_secret_markers_are_case_insensitive():
    renderer = SynthesisRenderer()
    for content in (
        "MY KEY BEGINS SK-12345",
        "header X-API-KEY: abc",
        "Password=s3cret",
        "Secret=abc",
        "Key=abc123",
        "jwt eyJhbGciOiJIUzI1NiJ9",
        "pem -----BEGIN CERTIFICATE-----",
    ):
        _raises(SynthesisRenderError, renderer.render, _result_bypass(content=content))


def test_bypass_helpers_skip_field_validation():
    # Sanity: model_construct really bypasses the models secret validators, so
    # the renderer's own guard (not the field layer) is what the above tests hit.
    result = _result_bypass(content="the token is sk-secret")
    assert "sk-secret" in result.content


def test_render_oversized_output_raises_synthesis_render_error():
    result = _result(content="x" * 2000)
    renderer = SynthesisRenderer(max_output_chars=100)
    err = _raises(SynthesisRenderError, renderer.render, result)
    assert "limit is 100" in str(err)


def test_render_truncated_never_raises_on_oversized_input():
    result = _result(content="x" * 2000)
    renderer = SynthesisRenderer(max_output_chars=100)
    output = renderer.render_truncated(result, limit=50)
    assert isinstance(output, str)
    assert ("x" * 50) + "…" in output


def test_render_truncated_still_rejects_secret_marker():
    # Only the length check is exempt; the credential scan still fails closed.
    result = _result_bypass(content="the key is sk-proj-abc123")
    _raises(SynthesisRenderError, SynthesisRenderer().render_truncated, result, 100)


def test_benign_long_content_truncates_cleanly():
    content = (
        "The final reconciled balance across all treasury accounts on "
        "2026-08-08 totals $1,204,500."
    ) * 5
    output = SynthesisRenderer().render_truncated(_result(content=content), limit=60)
    assert output.startswith("# recursive result")
    assert content[:60] + "…" in output


def test_render_is_deterministic():
    citations = (_citation("c1", reference_id="r1"), _citation("c2", reference_id="r2"))
    result = _result(citations=citations)
    renderer = SynthesisRenderer()
    assert renderer.render(result) == renderer.render(result)


def test_renderer_rejects_non_positive_max_output_chars():
    _raises(ValueError, SynthesisRenderer, max_output_chars=0)
