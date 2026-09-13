"""Deterministic claim extraction for grounded-synthesis verification (ADR-008 D7).

Before an answer surfaces, the harness splits the synthesized content into
claim statements — one per sentence — so the later verification stages can
match each claim against its evidence references. This module is the
extraction stage: deterministic, model-free (it never calls an LLM), and
dependency-light (``models.py`` excepted for :class:`ClaimStatement`).

Extraction rules (documented, tested):

* **Skipped lines**: empty lines, lines that are pure whitespace, markdown
  headers (start with ``#``), citation/evidence lines (start with ``[ref:``),
  and numbered-list lines (start with one or more digits followed by a ``.``,
  e.g. ``1.`` or ``10.``). A numbered list item is skipped in full even when
  it contains prose after the number.
* **Sentence split**: each remaining line is split on the sentence boundaries
  ``'. '``, ``'! '``, ``'? '``. The boundary punctuation is part of the split
  delimiter and is consumed, so a sentence followed by ``'. '`` loses its
  period; only a final sentence not followed by a boundary retains its
  trailing punctuation.
* **Minimum length**: every candidate sentence is trimmed, and anything
  shorter than :data:`MIN_CLAIM_CHARS` (8) is noise and dropped.
* **Return values**: empty or whitespace-only content returns ``[]``, and
  content made up entirely of skippable structural lines also returns ``[]`` —
  there is nothing claim-shaped to verify, so there is no unparseable result
  to block. When a NON-empty content contains claim-shaped lines but every
  candidate sentence is below ``MIN_CLAIM_CHARS``, extraction raises
  :class:`ClaimExtractionError` (fail-closed: an unparseable synthesis result
  cannot pass verification).
* **Secrets**: constructing a :class:`ClaimStatement` is where ``models.py``
  rejects secret-shaped sentences with ``VerificationUnsafe``. That exception
  is deliberately NOT caught here — a secret-shaped claim must never proceed,
  so the failure propagates to the caller.
"""

from __future__ import annotations

import re

from services.model_runtime.verification.models import ClaimStatement

__all__ = [
    "ClaimExtractionError",
    "MIN_CLAIM_CHARS",
    "ClaimExtractor",
]

# Claims shorter than this are noise and dropped. The constant is module-level
# so the extractor and callers share a single source of truth.
MIN_CLAIM_CHARS: int = 8

# Sentence boundary: '. ', '! ', '? '. The punctuation is consumed as part of
# the split delimiter, so only a trailing sentence keeps its punctuation.
_SENTENCE_BOUNDARY = re.compile(r"[.!?] ")

# A numbered-list line such as "1." or "10." (digit(s) followed by a period).
_NUMBERED_LINE = re.compile(r"^\d+\.")

# A standalone citation/evidence line, e.g. "[ref:tx-1234]".
_CITATION_PREFIX = "[ref:"


class ClaimExtractionError(Exception):
    """Raised when a non-empty synthesis result yields no extractable claims."""


class ClaimExtractor:
    """Splits synthesis content into claim statements.

    Deterministic and model-free: it performs pure string processing and never
    calls an LLM, so the same input always yields the same claims.
    """

    def extract(self, content: str) -> list[ClaimStatement]:
        """Split ``content`` into claim statements.

        See the module docstring for the exact skip rules, sentence-split
        behavior, and the fail-closed ``ClaimExtractionError`` contract.
        """
        if not content or not content.strip():
            # Empty or whitespace-only content: nothing to verify.
            return []

        claims: list[ClaimStatement] = []
        has_claim_shaped_lines = False

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if self._is_skippable_line(line):
                continue
            has_claim_shaped_lines = True
            for sentence in _SENTENCE_BOUNDARY.split(line):
                text = sentence.strip()
                if len(text) < MIN_CLAIM_CHARS:
                    continue
                # ClaimStatement construction is where models.py rejects
                # secret-shaped text (VerificationUnsafe); it propagates by
                # design so a secret-shaped claim never proceeds.
                claims.append(ClaimStatement(text=text))

        if not has_claim_shaped_lines:
            # Everything was structural (headers/citations/numbered/blank):
            # there is no claim-shaped text to verify, so return [] rather than
            # failing closed on a degenerate input.
            return []
        if not claims:
            raise ClaimExtractionError(
                "synthesis content produced no claim at or above "
                f"MIN_CLAIM_CHARS={MIN_CLAIM_CHARS}; unparseable result cannot "
                "pass verification (fail closed)"
            )
        return claims

    @staticmethod
    def _is_skippable_line(line: str) -> bool:
        """True for markdown headers, citation lines, and numbered-list lines."""
        if line.startswith("#"):
            return True
        if line.startswith(_CITATION_PREFIX):
            return True
        if _NUMBERED_LINE.match(line):
            return True
        return False
