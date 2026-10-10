"""Deterministic credential-leak sweep over synthesis content and citations.

ADR-008 D7/D8 — the final fail-closed guard. A synthesis result must NEVER
carry credential-shaped material into downstream consumers: raw API keys,
AWS access key IDs, bearer tokens, PEM blocks, auth headers, password/secret
assignments, or JWT-shaped blobs. This module is the last-line detector swept
over synthesis content and citation excerpts before anything crosses a trust
boundary.

The scan is deterministic and dependency-light: pure substring + position
matching against :data:`LEAK_MARKERS`, case-insensitive, with no model calls
and no pydantic dependency. :class:`LeakHit` is a plain frozen dataclass, and
:class:`SecretLeakDetector` returns ``[]`` when the scanned text is clean.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "LEAK_MARKERS",
    "LeakHit",
    "SecretLeakDetector",
]

# Credential-shaped substrings a synthesized response must never contain.
# Stored as-written and matched case-insensitively so "SK-", "akia",
# "BEARER ", "eyJ" etc. all trip the detector. "key=" is deliberately
# narrower than "key" so benign words like "keychain" do not false-positive.
LEAK_MARKERS: tuple[str, ...] = (
    "sk-",
    "AKIA",
    "Bearer ",
    "-----BEGIN",
    "Authorization:",
    "X-Api-Key:",
    "password=",
    "secret=",
    "key=",
    "eyJ",
)


@dataclass(frozen=True)
class LeakHit:
    """One credential-shaped marker found in scanned text."""

    marker: str
    #: 0-based start index of the marker in the ORIGINAL (not lowered) text.
    position: int


class SecretLeakDetector:
    """Scans text for credential-shaped markers. Returns ``[]`` when clean.

    Matching is case-insensitive. Each marker's FIRST occurrence is recorded;
    subsequent occurrences of the SAME marker are ignored, while DIFFERENT
    markers are each reported once. ``position`` is the index of the matched
    marker's first character in the original string — positions are read off
    the lowered text, which is identical to the original here because every
    marker is ASCII and ASCII lowercasing is a 1:1 byte mapping.
    """

    def detect(self, text: str) -> list[LeakHit]:
        """Return a ``LeakHit`` per distinct marker present in ``text``."""
        lowered = text.lower()
        hits: list[LeakHit] = []
        for marker in LEAK_MARKERS:
            position = lowered.find(marker.lower())
            if position >= 0:
                hits.append(LeakHit(marker=marker, position=position))
        return hits

    def is_clean(self, text: str) -> bool:
        """True when no credential-shaped marker appears in ``text``."""
        return self.detect(text) == []
