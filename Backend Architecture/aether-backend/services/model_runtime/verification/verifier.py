"""Fail-closed verification orchestrator (ADR-008 D7) — faithfulness + leak gate.

The verification engine is the D7 gate every synthesized answer passes through
BEFORE it may surface: claims extracted from the synthesis content are checked
against the citations the model was grounded on, and the content plus every
citation excerpt is swept for credential-shaped leaks. A result that is
unfaithful (an unsupported claim) or leaks a credential is blocked (fail
closed) and is never presented as verified truth.

Concurrency note: the verification package's sibling modules (``models``,
``claims``, ``faithfulness``, ``leaks``) land in the same commit effort, and
``models.py`` is replaced by Commit 10-A's real contract. This module imports
``synthesis.models`` eagerly (already landed) and resolves the verification
siblings lazily inside the methods that need them, so the module imports
cleanly even while those siblings are landing. In particular,
:meth:`VerificationEngine.__init__` lazily imports the default extractor,
checker, and leak detector, and :meth:`VerificationEngine.run` lazily imports
``VerificationResult`` and ``ClaimExtractionError``.

Security posture: ``run`` and ``enforce`` NEVER log synthesis content or
credentials. They fail closed with typed exceptions instead of emitting the
offending text downstream.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from services.model_runtime.synthesis.models import SynthesisResult

if TYPE_CHECKING:
    from services.model_runtime.synthesis.models import EvidenceCitation
    from services.model_runtime.verification.claims import ClaimExtractor
    from services.model_runtime.verification.faithfulness import FaithfulnessChecker
    from services.model_runtime.verification.leaks import SecretLeakDetector
    from services.model_runtime.verification.models import (
        ClaimStatement,
        CitationCheck,
        VerificationResult,
    )

#: Inline citation marker in synthesized prose, e.g. ``[ref:tx-1234]``. The
#: synthesis prompt instructs the model to cite ``[ref:<reference_id>]``; each
#: extracted claim is verified ONLY against the citations it references
#: (cite-aware grounding), never against the full evidence set.
_REF_MARKER = re.compile(r"\[ref:([^\]]+)\]")

__all__ = [
    "VerificationFailure",
    "VerificationError",
    "VerificationEngine",
]


class VerificationFailure(Exception):
    """Raised by :meth:`VerificationEngine.enforce` when verification fails closed.

    The synthesis is not faithful (an unsupported claim) or leaked credential-
    shaped material (ADR-008 D7); the caller must not act on it.
    """


class VerificationError(Exception):
    """Raised by :meth:`VerificationEngine.run` when verification cannot complete.

    For example, claim extraction raises ``ClaimExtractionError`` (an
    unparseable synthesis result cannot pass verification). Fail-closed: a
    verification stage that cannot run must fail the request.
    """


class VerificationEngine:
    """Runs claim faithfulness checks plus the credential-leak sweep.

    The components (extractor, faithfulness checker, leak detector) are
    injectable for composition and tests. Defaults are resolved lazily so this
    module imports independently of the verification siblings' landing order.
    """

    def __init__(
        self,
        *,
        extractor: ClaimExtractor | None = None,
        checker: FaithfulnessChecker | None = None,
        leaks: SecretLeakDetector | None = None,
    ) -> None:
        if extractor is None:
            # Lazy import: verification/claims.py (sibling B) lands concurrently.
            from services.model_runtime.verification.claims import ClaimExtractor

            extractor = ClaimExtractor()
        if checker is None:
            # Lazy import: verification/faithfulness.py (sibling C) lands
            # concurrently.
            from services.model_runtime.verification.faithfulness import (
                FaithfulnessChecker,
            )

            checker = FaithfulnessChecker()
        if leaks is None:
            # Lazy import: verification/leaks.py (sibling E) may land after this
            # module; the lazy import keeps VerificationEngine importable
            # independently of E's presence on disk.
            from services.model_runtime.verification.leaks import SecretLeakDetector

            leaks = SecretLeakDetector()
        self._extractor = extractor
        self._checker = checker
        self._leaks = leaks

    def run(self, result: SynthesisResult) -> VerificationResult:
        """Run claim faithfulness + leak verification over a synthesis result.

        Steps:

        1. ``claims = extractor.extract(result.content)`` — a
           ``ClaimExtractionError`` becomes :class:`VerificationError`.
        2. ``checks = _check_cited(claims, result.citations)`` — cite-aware
           grounding: each claim is checked ONLY against the citations it cites
           (inline ``[ref:...]`` markers and/or ``claim.evidence_refs``); a
           claim that cites nothing is checked against no citations and is
           therefore unsupported.
        3. Sweep the content and every citation excerpt with the leak detector.
        4. ``leak_detected = bool(hits)``.
        5. ``faithful`` requires: a NON-empty output must have yielded claims
           (a hallucinated numbered list with nothing to verify is rejected,
           not "verified"), every check must be supported, and no leak may be
           present:
           ``faithful = not zero_claims_from_content and all(c.supported for c
           in checks) and not leak_detected``.
        6. Return a :class:`VerificationResult` carrying the claims, checks,
           the faithfulness/leak dispositions, and a fresh UTC timestamp.

        Edge cases (documented):

        * A non-empty model output that yields zero claims (e.g. content made
          entirely of numbered-list/citation/header lines) is a REJECTION:
          ``faithful=False`` — there is nothing to verify, so the output cannot
          be presented as verified truth.
        * Empty/whitespace-only output yields zero claims and zero checks, so
          ``all(...)`` over the empty check sequence is ``True`` and
          ``faithful`` then depends only on ``leak_detected``.

        Never logs content or credentials.
        """
        # Lazy import: verification/models.py is replaced by Commit 10-A's real
        # contract; resolve it at call time so this module imports
        # independently. ClaimExtractionError comes from sibling B.
        from services.model_runtime.verification.models import VerificationResult
        from services.model_runtime.verification.claims import ClaimExtractionError

        try:
            claims = self._extractor.extract(result.content)
        except ClaimExtractionError as err:
            raise VerificationError(
                f"verification could not complete for request {result.request_id}: "
                "claim extraction failed"
            ) from err

        checks = self._check_cited(claims, result.citations)

        # Credential sweep over the content AND every citation excerpt.
        leak_hits = list(self._leaks.detect(result.content))
        for citation in result.citations:
            leak_hits.extend(self._leaks.detect(citation.excerpt))

        leak_detected = bool(leak_hits)
        # A NON-empty output that yields zero claims is a rejection: a
        # hallucinated numbered list would otherwise pass with nothing to
        # verify (all([]) is True). Empty output keeps the leak-only gate.
        zero_claims_from_content = bool(result.content.strip()) and not claims
        faithful = (
            not zero_claims_from_content
            and all(check.supported for check in checks)
            and not leak_detected
        )

        return VerificationResult(
            request_id=result.request_id,
            claims=tuple(claims),
            checks=tuple(checks),
            faithful=faithful,
            leak_detected=leak_detected,
            created_at=datetime.now(timezone.utc),
        )

    def _check_cited(
        self,
        claims: Sequence[ClaimStatement],
        citations: Sequence[EvidenceCitation],
    ) -> list[CitationCheck]:
        """Cite-aware grounding: check each claim ONLY against its cited citations.

        A claim's cited references are the inline ``[ref:...]`` markers in its
        text plus any ``claim.evidence_refs`` a custom extractor populated.
        Claims are grouped by their scoped citation set so the checker runs
        once per distinct scope (one :class:`CitationCheck` per claim, in
        deterministic order). A claim that cites nothing — or cites only
        reference ids absent from ``citations`` — is checked against NO
        citations and is therefore unsupported (fail-closed): it cannot be
        traced to retrieved evidence.
        """
        by_ref = {citation.reference_id: citation for citation in citations}
        buckets: dict[tuple[str, ...], list[ClaimStatement]] = {}
        for claim in claims:
            refs = self._cited_reference_ids(claim)
            scoped_ids = tuple(sorted(ref for ref in refs if ref in by_ref))
            buckets.setdefault(scoped_ids, []).append(claim)

        checks: list[CitationCheck] = []
        for scoped_ids, bucket in buckets.items():
            scoped = [by_ref[ref_id] for ref_id in scoped_ids]
            checks.extend(self._checker.check(bucket, scoped))
        return checks

    @staticmethod
    def _cited_reference_ids(claim: ClaimStatement) -> set[str]:
        """Reference ids a claim cites: inline markers plus ``evidence_refs``."""
        refs: set[str] = set(claim.evidence_refs)
        for raw in _REF_MARKER.findall(claim.text):
            ref = raw.strip()
            if ref:
                refs.add(ref)
        return refs

    def enforce(self, result: SynthesisResult) -> VerificationResult:
        """Fail-closed gate: ``run()`` then raise unless the result is faithful.

        Raises :class:`VerificationFailure` when the verified result is not
        faithful or a leak was detected. Returns the verified
        :class:`VerificationResult` when the synthesis passed. Callers use
        ``enforce`` BEFORE acting on a synthesis; a faithful result may then be
        acted on, an unfaithful one never is.
        """
        vresult = self.run(result)
        if not vresult.faithful or vresult.leak_detected:
            raise VerificationFailure(
                f"synthesis {result.request_id} failed verification: "
                f"faithful={vresult.faithful}, leak_detected={vresult.leak_detected}"
            )
        return vresult
