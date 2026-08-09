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

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from services.model_runtime.synthesis.models import SynthesisResult

if TYPE_CHECKING:
    from services.model_runtime.verification.claims import ClaimExtractor
    from services.model_runtime.verification.faithfulness import FaithfulnessChecker
    from services.model_runtime.verification.leaks import SecretLeakDetector
    from services.model_runtime.verification.models import VerificationResult

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
        2. ``checks = checker.check(claims, result.citations)``.
        3. Sweep the content and every citation excerpt with the leak detector.
        4. ``leak_detected = bool(hits)``;
           ``faithful = all(c.supported for c in checks) and not leak_detected``.
        5. Return a :class:`VerificationResult` carrying the claims, checks,
           the faithfulness/leak dispositions, and a fresh UTC timestamp.

        Edge case (documented): if extraction yields zero claims (and therefore
        zero checks), ``all(...)`` over an empty sequence is ``True``, so
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

        checks = self._checker.check(claims, result.citations)

        # Credential sweep over the content AND every citation excerpt.
        leak_hits = list(self._leaks.detect(result.content))
        for citation in result.citations:
            leak_hits.extend(self._leaks.detect(citation.excerpt))

        leak_detected = bool(leak_hits)
        faithful = all(check.supported for check in checks) and not leak_detected

        return VerificationResult(
            request_id=result.request_id,
            claims=tuple(claims),
            checks=tuple(checks),
            faithful=faithful,
            leak_detected=leak_detected,
            created_at=datetime.now(timezone.utc),
        )

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
