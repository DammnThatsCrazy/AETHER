"""Bounded, injection-guarded synthesis prompt built from a ``ContextBundle``.

ADR-008 D6 — grounded-synthesis prompt builder (Agent E).

The rendered prompt is the ONLY text a grounded-synthesis model sees: it is
assembled deterministically from the retrieval evidence, carries per-item
``[ref:<reference_id>]`` citations, never carries credentials, and is strictly
bounded in size. This module only renders text; it never executes anything.

Builds against Agent A's evidence module (same commit, ADR-008 D6),
``services.model_runtime.context.evidence``. Agent A's field layer already
rejects credential-shaped text at construction time via ``EvidenceUnsafe``;
this builder's ``InjectionGuardError`` guard is the prompt-surface
defense-in-depth for credentials and is the sole guard for prompt-injection
tokens, which the evidence layer does not filter.
"""

from __future__ import annotations

import re

from services.model_runtime.context.evidence import ContextBundle, EvidenceUnsafe

# Fixed prompt skeleton. ``<reference_id>`` is literal placeholder text teaching
# the citation format; each evidence block supplies the concrete reference.
_PRE_AMBLE = "Synthesize ONLY from the evidence below. Cite [ref:<reference_id>]"
_INSTRUCTIONS_HEADER = "Instructions:"
_UNSUPPORTED_LINE = "If the evidence is insufficient, answer 'unsupported'."

# Prompt-injection tokens, stored lowercased and matched case-insensitively.
# Evidence content is echoed back verbatim by the model, so these must never
# reach the synthesis model.
_VIOLATION_TOKENS: tuple[str, ...] = (
    "ignore previous instructions",
    "<|sys|>",
    "system prompt:",
    "jailbreak",
    "<script",
)

# Credential markers, stored lowercased and matched case-insensitively.
# Agent A's field layer also rejects these (``EvidenceUnsafe``); this list is
# the prompt-surface defense-in-depth and deliberately mirrors A's markers.
_CREDENTIAL_MARKERS: tuple[str, ...] = (
    "sk-",
    "akia",
    "bearer ",
    "authorization:",
    "x-api-key:",
)

# Default hard cap on the rendered prompt, in characters.
MAX_PROMPT_CHARS: int = 12000

# A reference id is a bounded token of word characters, dots, colons, slashes,
# underscores, or hyphens — never whitespace, brackets, angle brackets, quotes,
# or control characters. The id is embedded inside the ``[ref:...]`` template,
# so a crafted value must not be able to break out of the citation marker or
# smuggle prompt text into the model input.
_REFERENCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/_-]*$")


class PromptSizeError(Exception):
    """Raised when the rendered prompt exceeds the configured character limit."""


class InjectionGuardError(Exception):
    """Raised when a violation token or credential marker is found in the input."""


class GroundedPromptBuilder:
    """Render the bounded synthesis prompt for a ``ContextBundle``.

    Deterministic: item blocks appear in ``bundle.evidence.items`` order.
    Pure sync; only renders text.
    """

    def __init__(self, *, max_chars: int = MAX_PROMPT_CHARS) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        self._max_chars = max_chars

    def build(self, bundle: ContextBundle) -> str:
        """Render a guarded, bounded prompt.

        Raises:
            InjectionGuardError: a violation token or credential marker was
                found in ``item.content``/``item.source``/``query``/
                ``synthesis_instructions``.
            PromptSizeError: the rendered prompt exceeds ``max_chars``.
        """
        self._guard(bundle)
        result = self._render(bundle)
        if len(result) > self._max_chars:
            raise PromptSizeError(
                f"rendered prompt is {len(result)} chars; limit is {self._max_chars}"
            )
        return result

    def _guard(self, bundle: ContextBundle) -> None:
        """Reject injection tokens and credential markers in every input field.

        Every ``reference_id`` is additionally validated against the bounded
        ``[ref:...]`` token format BEFORE it is embedded into the template, so
        a crafted id cannot break out of the citation marker or smuggle prompt
        text into the model input.
        """
        candidates: list[str] = [bundle.query]
        if bundle.synthesis_instructions:
            candidates.append(bundle.synthesis_instructions)
        for item in bundle.evidence.items:
            self._validate_reference_id(item.reference_id)
            candidates.append(item.reference_id)
            candidates.append(item.content)
            candidates.append(item.source)

        for text in candidates:
            lowered = text.lower()
            for token in _VIOLATION_TOKENS:
                if token in lowered:
                    raise InjectionGuardError(
                        f"prompt-injection token {token!r} found in synthesis input"
                    )
            for marker in _CREDENTIAL_MARKERS:
                if marker in lowered:
                    raise InjectionGuardError(
                        f"credential marker {marker!r} found in synthesis input"
                    )

    @staticmethod
    def _validate_reference_id(reference_id: str) -> None:
        """Reject a reference id that could break out of the ``[ref:...]`` template.

        The value is embedded verbatim into ``[ref:<reference_id>]``, so it
        must be a bounded token of word characters, dots, colons, slashes,
        underscores, or hyphens. Whitespace, brackets, angle brackets, quotes,
        and control characters are rejected before the prompt is rendered.
        """
        if not _REFERENCE_ID_RE.match(reference_id):
            raise InjectionGuardError(
                f"unsafe reference_id {reference_id!r} in synthesis input"
            )

    def _render(self, bundle: ContextBundle) -> str:
        """Pure render of the prompt (called by ``build`` after the guard pass)."""
        parts: list[str] = [_PRE_AMBLE]
        if bundle.synthesis_instructions:
            parts.append(f"{_INSTRUCTIONS_HEADER}\n{bundle.synthesis_instructions}")
        for item in bundle.evidence.items:
            parts.append(
                f"[ref:{item.reference_id}] (source: {item.source})\n{item.content}"
            )
        parts.append(_UNSUPPORTED_LINE)
        return "\n\n".join(parts)
