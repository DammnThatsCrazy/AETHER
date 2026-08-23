"""Deterministic, fail-closed faithfulness verification for grounded synthesis.

ADR-008 D7 — before an answer surfaces, the harness checks that each claim in
the synthesized content is *grounded* in the retrieved evidence. This module
owns the token-overlap faithfulness check:

* A claim is **SUPPORTED** only when it shares at least one *significant
  token* with at least one citation excerpt.
* A *significant token* is a lowercased, non-stopword token of length >= 3
  characters that is not a bare number or date. ``revenue`` and ``grew``
  count; ``the``, ``20%``, and ``2024-01-15`` do not.
* If there are **no citations at all**, every claim is **unsupported**
  (fail closed: nothing retrieved, nothing verified).
* A claim with **no significant tokens** (a stopword-only phrase such as
  ``"This is it"``, or a bare number/date) is **unsupported** — a degenerate
  claim cannot be verified and is never presented as truth.

When a claim is unsupported, its check still points at the *best-matching*
citation (the one with the highest shared-significant-token count; first wins
ties) so an operator can see the closest evidence behind a failed claim. With
no citations the reference id is the empty string.

The check is deterministic and dependency-light: pure string processing, no
model calls. It consumes the verification contract types from ``models.py``
(``ClaimStatement``, ``CitationCheck``) and the synthesis citation type
(``EvidenceCitation``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from services.model_runtime.verification.models import CitationCheck

if TYPE_CHECKING:  # pragma: no cover - type-only, resolved at type-check time
    from services.model_runtime.synthesis.models import EvidenceCitation
    from services.model_runtime.verification.models import ClaimStatement

__all__ = [
    "FaithfulnessCheckError",
    "STOPWORDS",
    "FaithfulnessChecker",
]

#: A small English stopword set. A token in this set (matched case-insensitively)
#: never counts toward a shared-token match.
STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on",
        "for", "and", "or", "it", "this", "that", "with", "as", "at", "by",
        "from", "be", "been", "will", "would", "can", "could", "do", "does",
        "did", "has", "have", "had", "not", "no", "but", "its", "their",
        "them", "they", "we", "you", "i", "my", "your",
    }
)

#: Tokens shorter than this are noise and never count toward a match.
_MIN_SIGNIFICANT_LEN = 3

#: The matching method label recorded on every citation check produced here.
_METHOD = "token-overlap"

#: Punctuation stripped from the ends of a raw token before significance tests.
_TOKEN_STRIP_CHARS = ".,;:!?\"'()[]{}<>"

#: Numeric/date separators: a token made only of digits plus these separators
#: is a bare number/date and is never a significant token.
_NUMERIC_DATE_SEPARATORS = frozenset(".,:/-%_")


class FaithfulnessCheckError(Exception):
    """Raised when faithfulness verification cannot be performed.

    Reserved for the fail-closed machinery: a verification stage that cannot
    run must fail the request rather than silently passing claims through.
    """


def _is_numeric_or_date(token: str) -> bool:
    """True when ``token`` is a bare number/date (digits plus separators)."""
    return any(ch.isdigit() for ch in token) and all(
        ch.isdigit() or ch in _NUMERIC_DATE_SEPARATORS for ch in token
    )


def _significant_tokens(text: str) -> frozenset[str]:
    """Lowercased, non-stopword, >=3-char, non-numeric/date tokens in ``text``."""
    tokens: set[str] = set()
    for raw in text.lower().split():
        token = raw.strip(_TOKEN_STRIP_CHARS)
        if len(token) < _MIN_SIGNIFICANT_LEN:
            continue
        if token in STOPWORDS:
            continue
        if _is_numeric_or_date(token):
            continue
        tokens.add(token)
    return frozenset(tokens)


def _shared_count(
    claim_tokens: frozenset[str],
    excerpt_tokens: frozenset[str],
) -> int:
    """Number of significant tokens shared between a claim and an excerpt."""
    return len(claim_tokens & excerpt_tokens)


class FaithfulnessChecker:
    """Conservative, fail-closed token-overlap faithfulness checker.

    A claim is SUPPORTED only when it shares at least one significant token
    with at least one citation excerpt. If no citations exist, EVERY claim is
    unsupported.
    """

    def check(
        self,
        claims: Sequence[ClaimStatement],
        citations: Sequence[EvidenceCitation],
    ) -> list[CitationCheck]:
        """Verify every claim against the citation excerpts, fail-closed.

        Each result carries the *best-matching* citation's ``reference_id``
        (highest shared-significant-token count; first wins ties) — even when
        the claim is unsupported, so the nearest evidence is reported. With no
        citations the reference id is ``""`` and every claim is unsupported.
        """
        excerpt_tokens = [_significant_tokens(citation.excerpt) for citation in citations]
        checks: list[CitationCheck] = []
        for claim in claims:
            claim_tokens = _significant_tokens(claim.text)
            best_index = 0
            best_score = 0
            for index, tokens in enumerate(excerpt_tokens):
                score = _shared_count(claim_tokens, tokens)
                if score > best_score:
                    best_score = score
                    best_index = index
            reference_id = citations[best_index].reference_id if citations else ""
            checks.append(
                CitationCheck(
                    reference_id=reference_id,
                    claim_text=claim.text,
                    supported=best_score > 0,
                    method=_METHOD,
                )
            )
        return checks

    def supported_ratio(self, checks: Sequence[CitationCheck]) -> float:
        """Fraction of checks that are supported; ``0.0`` when there are none."""
        if not checks:
            return 0.0
        supported = sum(1 for check in checks if check.supported)
        return supported / len(checks)
