"""ADR-008 D7 verification/faithfulness — fail-closed verification barrel.

The verification layer is the D7 gate every synthesized answer passes through
BEFORE it may surface: claims extracted from the synthesis content are checked
against the citations the model was grounded on, and the content plus every
citation excerpt is swept for credential-shaped leaks. A result that is
unfaithful (an unsupported claim) or leaks a credential is blocked (fail
closed) and is never presented as verified truth. This barrel is the single
import surface the grounded-synthesis pipeline (later commits) consumes.

Ownership (same commit, ADR-008 D7):

* ``models`` — fail-closed verification contracts (:class:`VerificationUnsafe`,
  :data:`VERIFICATION_SECRET_MARKERS`, :class:`ClaimStatement`,
  :class:`CitationCheck`, :class:`VerificationRequest`,
  :class:`VerificationResult`);
* ``claims`` — deterministic claim extraction (:class:`ClaimExtractionError`,
  :data:`MIN_CLAIM_CHARS`, :class:`ClaimExtractor`);
* ``faithfulness`` — token-overlap faithfulness check
  (:class:`FaithfulnessCheckError`, :data:`STOPWORDS`,
  :class:`FaithfulnessChecker`);
* ``verifier`` — the D7 engine (:class:`VerificationFailure`,
  :class:`VerificationError`, :class:`VerificationEngine`);
* ``leaks`` — credential-leak sweep (:data:`LEAK_MARKERS`,
  :class:`LeakHit`, :class:`SecretLeakDetector`);
* ``service`` — the public facade (:class:`VerificationService`,
  :class:`VerificationServiceError`).

Security posture: verification is fail-closed by construction —
:class:`VerificationResult` defaults to ``faithful=False`` — and facade errors
are short, content-free, and never carry credentials.
"""

from __future__ import annotations

from services.model_runtime.verification.claims import (
    ClaimExtractionError,
    ClaimExtractor,
    MIN_CLAIM_CHARS,
)
from services.model_runtime.verification.faithfulness import (
    FaithfulnessCheckError,
    FaithfulnessChecker,
    STOPWORDS,
)
from services.model_runtime.verification.leaks import (
    LEAK_MARKERS,
    LeakHit,
    SecretLeakDetector,
)
from services.model_runtime.verification.models import (
    VERIFICATION_SECRET_MARKERS,
    CitationCheck,
    ClaimStatement,
    VerificationRequest,
    VerificationResult,
    VerificationUnsafe,
)
from services.model_runtime.verification.service import (
    VerificationService,
    VerificationServiceError,
)
from services.model_runtime.verification.verifier import (
    VerificationEngine,
    VerificationError,
    VerificationFailure,
)

__all__ = [
    # verification/models.py — fail-closed verification contracts
    "VerificationUnsafe",
    "VERIFICATION_SECRET_MARKERS",
    "ClaimStatement",
    "CitationCheck",
    "VerificationRequest",
    "VerificationResult",
    # verification/claims.py — deterministic claim extraction
    "ClaimExtractionError",
    "MIN_CLAIM_CHARS",
    "ClaimExtractor",
    # verification/faithfulness.py — token-overlap faithfulness check
    "FaithfulnessCheckError",
    "STOPWORDS",
    "FaithfulnessChecker",
    # verification/verifier.py — the D7 engine
    "VerificationFailure",
    "VerificationError",
    "VerificationEngine",
    # verification/leaks.py — credential-leak sweep
    "LEAK_MARKERS",
    "LeakHit",
    "SecretLeakDetector",
    # verification/service.py — the public facade
    "VerificationService",
    "VerificationServiceError",
]
