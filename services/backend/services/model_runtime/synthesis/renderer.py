"""Grounded-synthesis result renderer (ADR-008 D6, Agent E).

Renders a :class:`SynthesisResult` as bounded, grounded markdown for the API
layer. The frontend Aether/Kyber surface renders sanitized evidence (see
``frontend/aether/src/features/model-selection/EvidenceReferences.tsx`` for the
pattern); this renderer mirrors that discipline server-side so the API never
emits credential material or unbounded payloads.

Security posture:

- Credential leakage (``sk-`` keys, AWS access keys, bearer tokens, PEM
  blocks, auth headers, JWT-shaped blobs, ``password=/secret=/key=`` forms) is
  re-checked on the model-echoed fields (content and every citation excerpt)
  via :class:`SynthesisRenderError`. Sibling A's field validators already
  reject these at construction time; this scan is the render-surface
  defense-in-depth and is strictly fail-closed: if a marker is present in any
  model-echoed field, nothing is emitted.
- Output size is bounded: :meth:`SynthesisRenderer.render` raises when the
  assembled string exceeds ``max_output_chars``; :meth:`SynthesisRenderer.render_truncated`
  caps the content section instead and never raises for length.

Mirrors the frontend evidence surface in two ways: the ``## Evidence`` section
is omitted when a result carries no citations (the frontend renders nothing for
an empty evidence list), and each excerpt is truncated to 160 chars with ``…``
before display.

Cross-commit note: this module is built against sibling A's
``synthesis/models.py`` contract (``SynthesisResult(request_id, plan_kind,
content, citations, created_at)`` and ``EvidenceCitation(reference_id, source,
tenant_id, excerpt)``). The model types are referenced only under
``TYPE_CHECKING`` so this renderer imports and lints cleanly while sibling A is
still landing; the render surface reads attributes directly (duck-typed) and
needs no runtime model import. The credential-marker list mirrors and extends
sibling A's ``SYNTHESIS_SECRET_MARKERS``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from services.model_runtime.synthesis.models import (
        EvidenceCitation,
        SynthesisResult,
    )

__all__ = [
    "SynthesisRenderError",
    "DEFAULT_MAX_OUTPUT_CHARS",
    "SynthesisRenderer",
]

# Default hard cap on the rendered markdown, in characters.
DEFAULT_MAX_OUTPUT_CHARS: int = 16000

# Max excerpt length in a citation line; longer excerpts are truncated with "…".
_EXCERPT_MAX: int = 160

_ELLIPSIS = "…"

# Renderer-level credential markers, stored as-written and matched
# case-insensitively. The first seven mirror sibling A's
# ``SYNTHESIS_SECRET_MARKERS``; the ``password=/secret=/key=`` forms are added
# at the render surface so the API is at least as strict as the model layer
# (defense-in-depth).
_RENDERER_SECRET_MARKERS: tuple[str, ...] = (
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


class SynthesisRenderError(Exception):
    """Raised when a render would emit credential material or exceed bounds.

    Guards the API-facing output: the renderer never returns text that carries
    secret-shaped content, and :meth:`SynthesisRenderer.render` refuses to
    return output beyond the configured size cap.
    """


class SynthesisRenderer:
    """Render a ``SynthesisResult`` as grounded, secret-free markdown.

    Deterministic: citations appear in ``result.citations`` order, numbered
    ``1..n``. Pure sync; only renders text.
    """

    def __init__(self, *, max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS) -> None:
        if max_output_chars <= 0:
            raise ValueError("max_output_chars must be positive")
        self._max_output_chars = max_output_chars

    def render(self, result: SynthesisResult) -> str:
        """Render the full grounded markdown for a synthesis result.

        Format::

            # <plan_kind> result
            request: <request_id>

            <content>

            ## Evidence
            1. [ref:<reference_id>] (source: <source>) — <excerpt …>

        The ``## Evidence`` section is emitted only when ``result.citations`` is
        non-empty. Excerpts longer than 160 chars are truncated with ``…``.

        Raises:
            SynthesisRenderError: a credential marker is present anywhere in the
                assembled output, or the output exceeds ``max_output_chars``.
        """
        output = self._render_markdown(result)
        self._guard_output(_candidates(result))
        if len(output) > self._max_output_chars:
            raise SynthesisRenderError(
                f"rendered synthesis output is {len(output)} chars; "
                f"limit is {self._max_output_chars}"
            )
        return output

    def render_truncated(self, result: SynthesisResult, limit: int) -> str:
        """Render the same markdown with the content section capped at ``limit``.

        Only the content section is truncated (with ``…`` when it is longer than
        ``limit``); citation lines stay intact with their 160-char excerpt cap.
        The credential scan still applies and never raises for length — the
        caller controls the size bound.

        Raises:
            SynthesisRenderError: a credential marker is present anywhere in the
                assembled output. Never raises for length.
        """
        content = result.content
        if len(content) > limit:
            content = f"{content[: max(0, limit)]}{_ELLIPSIS}"
        output = self._render_markdown(result, content=content)
        self._guard_output(_candidates(result, content=content))
        return output

    def _render_markdown(self, result: SynthesisResult, *, content: str | None = None) -> str:
        """Pure render of the grounded markdown (called after the guard decisions)."""
        body = result.content if content is None else content
        parts: list[str] = [
            f"# {result.plan_kind} result",
            f"request: {result.request_id}",
            body,
        ]
        if result.citations:
            parts.append("## Evidence")
            for index, citation in enumerate(result.citations, start=1):
                parts.append(self._render_citation(index, citation))
        return "\n\n".join(parts)

    @staticmethod
    def _render_citation(index: int, citation: EvidenceCitation) -> str:
        """One numbered citation line: reference, source, bounded excerpt."""
        excerpt = _truncate_excerpt(citation.excerpt)
        return (
            f"{index}. [ref:{citation.reference_id}] "
            f"(source: {citation.source}) — {excerpt}"
        )

    @staticmethod
    def _guard_output(candidates: list[str]) -> None:
        """Reject when any credential marker appears in a model-echoed field.

        Candidates are exactly the fields a model may echo back verbatim — the
        content and each citation excerpt — re-checked at the render surface as
        defense-in-depth beyond the models field layer. Case-insensitive and
        fail-closed: any marker in any candidate blocks the whole render, never
        silently redacting a subset. Server-authoritative identifiers
        (``reference_id``, ``source``) are not model-echoed and are not scanned.
        """
        lowered_candidates = [candidate.lower() for candidate in candidates]
        for marker in _RENDERER_SECRET_MARKERS:
            marker_low = marker.lower()
            for lowered in lowered_candidates:
                if marker_low in lowered:
                    raise SynthesisRenderError(
                        f"credential marker {marker!r} found in rendered synthesis output"
                    )


def _candidates(result: SynthesisResult, *, content: str | None = None) -> list[str]:
    """The model-echoed fields to scan: content plus every citation excerpt.

    ``content`` overrides ``result.content`` when provided (``render_truncated``
    scans the truncated body actually being emitted).
    """
    body = result.content if content is None else content
    return [body] + [citation.excerpt for citation in result.citations]


def _truncate_excerpt(excerpt: str) -> str:
    """Truncate an excerpt to ``_EXCERPT_MAX`` chars, appending ``…`` when longer."""
    if len(excerpt) <= _EXCERPT_MAX:
        return excerpt
    return f"{excerpt[:_EXCERPT_MAX]}{_ELLIPSIS}"
