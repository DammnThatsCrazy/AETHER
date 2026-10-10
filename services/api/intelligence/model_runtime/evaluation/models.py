"""Evaluation-plane data models (ADR-008 D7/D8) — scoring harness inputs/outputs.

The evaluation plane scores the multi-model harness: canned, tenant-scoped
scenarios are run through the synthesis engine and scored for
faithfulness/accuracy/leak-safety. This module owns the data models that carry
those scenarios and their scored outcomes across trust boundaries.

Security invariants (MUST NOT violate):
- No secret material may enter any content-carrying field of
  :class:`EvaluationCase` (``query``, ``expected_ground_truth``, ``scenario``).
  Every such field is swept case-insensitively against
  :data:`EVALUATION_SECRET_MARKERS` and rejected with :class:`EvaluationUnsafe`
  so a credential cannot be laundered through a scenario into the harness.
- :class:`EvaluationReport` is fail-closed by construction: ``passed`` may be
  ``True`` only when every score passed AND no leak was detected. An
  inconsistent report (e.g. ``passed=True`` while a leak was flagged) is
  rejected at construction rather than emitted.

This module is self-contained — it imports nothing from sibling ``model_runtime``
modules — so it can be developed and tested in parallel with the rest of
Commit 11.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Substring markers that must never appear in evaluation content. They match
#: common provider secret/credential prefixes, auth headers, JWT-shaped blobs,
#: and password/secret assignments so the gate fails closed before a scenario
#: or its expected ground truth could be persisted or executed. ``"key="`` is
#: deliberately narrower than ``"key"`` so benign words like "keychain" do not
#: false-positive.
EVALUATION_SECRET_MARKERS: tuple[str, ...] = (
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


class EvaluationUnsafe(Exception):
    """Raised when evaluation content carries credential secret material."""


def _reject_secret_markers(value: str) -> str:
    """Raise ``EvaluationUnsafe`` when ``value`` carries any secret marker.

    Matching is case-insensitive so ``"SK-"``, ``"akia"``, ``"bearer "`` etc.
    all trip the gate. The marker is reported as-written in the raised
    exception so operators can see which pattern matched.
    """
    lowered = value.casefold()
    for marker in EVALUATION_SECRET_MARKERS:
        if marker.casefold() in lowered:
            raise EvaluationUnsafe(f"evaluation content contains a secret marker ({marker!r})")
    return value


class EvaluationCase(BaseModel):
    """A canned, tenant-scoped scenario run through the synthesis engine.

    Frozen and ``extra="forbid"`` so a scenario is immutable once authored and
    cannot smuggle arbitrary extra fields into the harness. ``query``,
    ``expected_ground_truth`` and ``scenario`` are swept for secret markers and
    rejected with :class:`EvaluationUnsafe` when one is present.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str
    case_id: str
    query: str  # the prompt posed to the synthesis engine
    expected_ground_truth: str  # the reference answer synthesized output is scored against
    scenario: str = ""  # optional scenario preamble; must not carry secret markers
    allowed_plan_kinds: tuple[str, ...] = (
        "summarize",
    )  # plan kinds the case is permitted to propose

    @field_validator("query", "expected_ground_truth", "scenario")
    @classmethod
    def _validate_no_secrets(cls, value: str) -> str:
        return _reject_secret_markers(value)


class EvaluationScore(BaseModel):
    """One scored metric for an evaluation case.

    ``passed`` is decided by the scoring engine against ``threshold`` using the
    strategy named in ``method`` (e.g. ``"exact-match"``, ``"token-overlap"``
    or ``"leak-scan"``); the model itself stays a plain carrier.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    value: float
    passed: bool
    threshold: float
    method: str = ""


class EvaluationReport(BaseModel):
    """Outcome of scoring one evaluation case.

    Fail-closed by construction (ADR-008 D7/D8): ``passed`` is ``True`` only
    when every score passed AND ``leak_detected`` is ``False``. The invariant
    is enforced at construction so a buggy consumer cannot emit a report that
    launder a leaked or inaccurate run as a pass.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    request_id: str
    scores: tuple[EvaluationScore, ...] = ()
    passed: bool
    leak_detected: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _passed_must_be_consistent(self) -> "EvaluationReport":
        all_scores_passed = all(score.passed for score in self.scores)
        expected = all_scores_passed and not self.leak_detected
        if self.passed != expected:
            raise ValueError(
                f"EvaluationReport.passed={self.passed} is inconsistent; "
                f"expected {expected} given scores and leak_detected={self.leak_detected}"
            )
        return self


__all__ = [
    "EvaluationUnsafe",
    "EVALUATION_SECRET_MARKERS",
    "EvaluationCase",
    "EvaluationScore",
    "EvaluationReport",
]
