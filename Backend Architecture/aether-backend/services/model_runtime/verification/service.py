"""VerificationService — public facade for the fail-closed verification gate.

ADR-008 D7: before a synthesized answer may surface it must pass the
verification/faithfulness gate — each claim checked against its cited evidence
references, plus a credential-leak sweep over the content and every citation
excerpt. ``VerificationService`` is the one-call entry point the grounded-
synthesis pipeline (later commits) consumes. It wraps the
:class:`~services.model_runtime.verification.verifier.VerificationEngine`
into two methods:

* ``verify`` — run the gate and return the
  :class:`~services.model_runtime.verification.models.VerificationResult`;
  ``VerificationError`` / ``VerificationUnsafe`` / ``ClaimExtractionError``
  become :class:`VerificationServiceError`.
* ``enforce`` — fail-closed gate: raise :class:`VerificationServiceError`
  (wrapping ``VerificationFailure``) unless the synthesis is faithful.

The facade never logs synthesis content or credentials: every raised message
is SHORT and content-free. ``result`` is typed with a string annotation so
this module imports independently of ``synthesis/``'s landing order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from services.model_runtime.verification.claims import ClaimExtractionError
from services.model_runtime.verification.models import VerificationUnsafe
from services.model_runtime.verification.verifier import (
    VerificationEngine,
    VerificationError,
    VerificationFailure,
)

if TYPE_CHECKING:  # pragma: no cover - type-only, resolved at type-check time
    from services.model_runtime.synthesis.models import SynthesisResult
    from services.model_runtime.verification.models import VerificationResult

__all__ = ["VerificationServiceError", "VerificationService"]


class VerificationServiceError(Exception):
    """Raised when verification cannot complete or fails closed.

    The message is short and never carries synthesis content or credentials —
    at most the request identifier — so a secret violation can never
    propagate its secret through the facade.
    """


class VerificationService:
    """Facade wrapping the D7 verification engine for synthesized answers.

    The engine is injectable for testing; when omitted a default
    :class:`VerificationEngine` is composed. ``result`` is a
    ``SynthesisResult``-shaped object; the annotation is a string so this
    module imports independently of ``synthesis/``'s landing order.
    """

    def __init__(self, *, engine: VerificationEngine | None = None) -> None:
        if engine is None:
            engine = VerificationEngine()
        self._engine = engine

    def verify(self, result: "SynthesisResult") -> "VerificationResult":
        """Run the verification gate; wrap fail-closed errors.

        Delegates to ``self._engine.run(result)``. When the engine cannot
        complete (``VerificationError`` — claim extraction failed) or the
        content carries a secret marker (``VerificationUnsafe`` /
        ``ClaimExtractionError``), the underlying error is wrapped in a short
        :class:`VerificationServiceError`; the content is never echoed.
        """
        try:
            return self._engine.run(result)
        except (VerificationError, VerificationUnsafe, ClaimExtractionError) as err:
            raise VerificationServiceError(
                "verification could not complete for request "
                f"{getattr(result, 'request_id', '<unknown>')}"
            ) from err

    def enforce(self, result: "SynthesisResult") -> "VerificationResult":
        """Fail-closed gate: raise unless the synthesis is faithful.

        Delegates to ``self._engine.enforce(result)``. An unfaithful or
        leaking result raises ``VerificationFailure`` inside the engine, and
        any verification error (``VerificationError`` / ``VerificationUnsafe``
        / ``ClaimExtractionError``) is wrapped as
        :class:`VerificationServiceError` so callers handle a single facade
        error type.
        """
        try:
            return self._engine.enforce(result)
        except (
            VerificationFailure,
            VerificationError,
            VerificationUnsafe,
            ClaimExtractionError,
        ) as err:
            raise VerificationServiceError(
                "synthesis failed verification for request "
                f"{getattr(result, 'request_id', '<unknown>')}"
            ) from err
