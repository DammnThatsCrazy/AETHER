"""Output-schema validation for the versioned task-profile runtime.

ADR-008 (Commit 7): task profiles declare an ``output_kind`` -- one of
``OUTPUT_KINDS`` in ``shared/model_governance/generated_task_profiles.py``
(``query_plan``, ``grounded_answer``, ``classification``, ``evidence_set``,
``structured_json``). The runtime must validate a model's output against the
declared kind BEFORE it surfaces to a caller.

Output-schema validation is a HARD guardrail: malformed or unsupported outputs
fail closed (``OutputValidation(valid=False)``) and are never surfaced.

Security constraints:
* This module never accepts or emits credentials. ``OutputValidation`` carries
  only ``kind`` / ``valid`` / ``errors``, and validation errors are static,
  content-free strings -- raw output text is never echoed into an error (a raw
  dump could leak a secret).
* Before ANY output kind may validate clean, the complete output -- every
  label, content field, and arbitrarily-nested structured-JSON value -- is
  swept through the package's canonical credential-marker scanner
  (:class:`SecretLeakDetector` in ``verification/leaks.py``). A single
  credential-shaped marker anywhere in the output fails the whole validation
  closed, regardless of how well-formed the structure is.
* A ``query_plan`` output must never carry raw query text: free-text SQL,
  Gremlin traversals, or Cypher/GraphQL expressions are rejected before the
  plan can be executed by the read-only Noesis runtime.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import BaseModel

from services.model_runtime.verification.leaks import SecretLeakDetector
from shared.model_governance.generated_task_profiles import OUTPUT_KINDS

__all__ = [
    "OutputValidation",
    "OutputValidationError",
    "OutputValidator",
    "SchemaOutputValidator",
]

# Modes a query-plan step may use. Anything else is free-text execution, which
# the read-only Noesis runtime must never run.
_ALLOWED_QUERY_PLAN_MODES = frozenset({"allowlisted", "deterministic"})

# Raw query-language fragments that must never appear inside a query plan. The
# plan is a data contract (``intent`` + ``mode``), not a query text dump. The
# strings are lowercase because the whole output is lowercased before scanning.
_FORBIDDEN_QUERY_FRAGMENTS = (
    "select ",  # SQL DQL/DML head
    "g.v(",  # Gremlin traversal step (normalized: "g.v(")
    "cypher",  # Neo4j/Cypher query language
    "graphql",  # GraphQL query language
)

# A citation marker embedded in a grounded answer: ``[ref:<reference_id>]``.
_CITATION_RE = re.compile(r"\[ref:([^\]]+)\]")

# Dispatch table: OUTPUT_KINDS entry -> SchemaOutputValidator checker method.
_KIND_CHECKS: dict[str, str] = {
    "query_plan": "_check_query_plan",
    "grounded_answer": "_check_grounded_answer",
    "classification": "_check_classification",
    "evidence_set": "_check_evidence_set",
    "structured_json": "_check_structured_json",
}

# Canonical credential-marker scanner shared across the model_runtime package
# (verification/leaks.py). The validator sweeps the COMPLETE output -- every
# label, content field, and arbitrarily-nested structured-JSON value -- through
# this detector before any output kind may validate clean. It is stateless and
# cheap, so one module-level instance is safe to share.
_SECRET_LEAK_DETECTOR = SecretLeakDetector()


class OutputValidationError(Exception):
    """Raised when a validator cannot process an output for a declared kind.

    The validator API is fail-closed by default (it returns an
    :class:`OutputValidation` with ``valid=False``); this exception is reserved
    for programmer errors, e.g. validating with a non-string kind.
    """


class OutputValidation(BaseModel, frozen=True):
    """Result of validating a model output against a declared output kind.

    Immutable: a validation verdict is a fact recorded once. ``errors`` holds
    static, content-free messages -- never raw output text.
    """

    kind: str
    valid: bool
    errors: tuple[str, ...] = ()


class OutputValidator(Protocol):
    """Protocol for output validators bound to a task profile's output kind."""

    def validate(self, kind: str, output: object) -> OutputValidation:
        """Return the validation verdict for ``output`` against ``kind``."""
        ...


def _contains_forbidden_query_text(output: object) -> bool:
    """True when the output's string form contains raw query-language text.

    The whole output is stringified and lowercased so a single embedded query
    fragment anywhere in the plan (any step) is caught. Any serialization
    surprise fails closed (returns True).
    """
    try:
        text = repr(output).lower()
    except Exception:  # pragma: no cover - fail closed on any repr surprise
        return True
    return any(fragment in text for fragment in _FORBIDDEN_QUERY_FRAGMENTS)


def _contains_secret_marker(output: object) -> bool:
    """True when any string field of ``output`` carries a credential marker.

    Recurses into nested dicts/lists so an arbitrarily deep ``structured_json``
    payload (or any other output kind) is fully covered: every label, content
    field, dict key, and list item is scanned. Matching is delegated to
    :class:`SecretLeakDetector` -- a case-insensitive substring scan against the
    canonical ``LEAK_MARKERS`` used across the model_runtime package. Fail
    closed: any marker found (or any scan surprise) rejects the whole output.
    """
    stack: list[object] = [output]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if not _SECRET_LEAK_DETECTOR.is_clean(key):
                    return True
                stack.append(value)
        elif isinstance(current, (list, tuple)):
            stack.extend(current)
        elif isinstance(current, str):
            if not _SECRET_LEAK_DETECTOR.is_clean(current):
                return True
    return False


def _matching_citations(answer: str, reference_ids: set[str]) -> int:
    """Count ``[ref:...]`` markers in ``answer`` that name a known reference."""
    return sum(1 for ref in _CITATION_RE.findall(answer) if ref.strip() in reference_ids)


class SchemaOutputValidator:
    """Structural validation of model outputs against declared output kinds.

    Implements one validation path per ``OUTPUT_KINDS`` entry. Every path is
    fail-closed: any structural or security violation produces an
    :class:`OutputValidation` with ``valid=False`` and content-free error
    strings. Unknown kinds are rejected so a registry typo cannot bypass the
    guardrail. Independently of the kind check, the complete output is swept
    for credential-shaped markers before it can ever validate clean.
    """

    def validate(self, kind: str, output: object) -> OutputValidation:
        """Validate ``output`` against the declared ``kind`` (fail-closed)."""
        if not isinstance(kind, str):
            raise OutputValidationError(
                f"output kind must be a string, got {type(kind).__name__}"
            )
        if kind not in OUTPUT_KINDS:
            return OutputValidation(
                kind=kind, valid=False, errors=("unknown output kind",)
            )
        errors = getattr(self, _KIND_CHECKS[kind])(output)
        if _contains_secret_marker(output):
            # Fail-closed credential sweep: NO output kind may surface
            # credential-shaped material, even when its structure is otherwise
            # valid. The error is static and content-free -- the matched marker
            # or secret value is never echoed.
            errors.append("output must not contain credential-shaped material")
        return OutputValidation(kind=kind, valid=not errors, errors=tuple(errors))

    def _check_query_plan(self, output: object) -> list[str]:
        errors: list[str] = []
        if not isinstance(output, dict) or "steps" not in output:
            errors.append("query_plan output must be a dict with a 'steps' list")
        else:
            steps = output["steps"]
            if not isinstance(steps, list):
                errors.append("query_plan 'steps' must be a list")
            else:
                for index, step in enumerate(steps):
                    if not isinstance(step, dict):
                        errors.append(f"query_plan step {index} must be a dict")
                        continue
                    intent = step.get("intent")
                    if not isinstance(intent, str) or not intent.strip():
                        errors.append(
                            f"query_plan step {index} must declare a non-empty 'intent'"
                        )
                    if step.get("mode") not in _ALLOWED_QUERY_PLAN_MODES:
                        errors.append(
                            f"query_plan step {index} 'mode' must be "
                            "allowlisted or deterministic"
                        )
        if _contains_forbidden_query_text(output):
            errors.append(
                "query_plan must not contain raw query text "
                "(SQL/Gremlin/Cypher/GraphQL)"
            )
        return errors

    def _check_grounded_answer(self, output: object) -> list[str]:
        errors: list[str] = []
        if not isinstance(output, dict):
            errors.append("grounded_answer output must be a dict")
            return errors
        answer = output.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            errors.append("grounded_answer 'answer' must be a non-empty string")
        evidence = output.get("evidence")
        reference_ids: set[str] = set()
        if not isinstance(evidence, list):
            errors.append("grounded_answer 'evidence' must be a list")
        else:
            for index, item in enumerate(evidence):
                if not isinstance(item, dict):
                    errors.append(
                        f"grounded_answer evidence item {index} must be a dict"
                    )
                    continue
                reference_id = item.get("reference_id")
                if not isinstance(reference_id, str) or not reference_id.strip():
                    errors.append(
                        f"grounded_answer evidence item {index} must have a "
                        "non-empty 'reference_id'"
                    )
                else:
                    reference_ids.add(reference_id)
                source = item.get("source")
                if not isinstance(source, str) or not source.strip():
                    errors.append(
                        f"grounded_answer evidence item {index} must have a "
                        "non-empty 'source'"
                    )
        if output.get("unsupported") is True:
            # Explicitly marked unsupported: the answer is allowed to carry no
            # citation markers (evidence may still be present but is optional).
            return errors
        if not errors and isinstance(answer, str):
            if _matching_citations(answer, reference_ids) == 0:
                errors.append(
                    "grounded_answer 'answer' must cite an evidence reference_id "
                    "([ref:...]) or be marked unsupported: true"
                )
        return errors

    def _check_classification(self, output: object) -> list[str]:
        errors: list[str] = []
        if not isinstance(output, dict):
            errors.append("classification output must be a dict")
            return errors
        label = output.get("label")
        if not isinstance(label, str) or not label.strip():
            errors.append("classification 'label' must be a non-empty string")
        confidence = output.get("confidence")
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)  # True/False are not confidence values
            or not (0 <= confidence <= 1)
        ):
            errors.append("classification 'confidence' must be a number between 0 and 1")
        return errors

    def _check_evidence_set(self, output: object) -> list[str]:
        errors: list[str] = []
        if not isinstance(output, list):
            errors.append("evidence_set output must be a list")
            return errors
        for index, item in enumerate(output):
            if not isinstance(item, dict):
                errors.append(f"evidence_set item {index} must be a dict")
                continue
            reference_id = item.get("reference_id")
            if not isinstance(reference_id, str) or not reference_id.strip():
                errors.append(
                    f"evidence_set item {index} must have a non-empty 'reference_id'"
                )
            content = item.get("content")
            if not isinstance(content, str) or not content.strip():
                errors.append(
                    f"evidence_set item {index} must have a non-empty 'content'"
                )
        return errors

    def _check_structured_json(self, output: object) -> list[str]:
        if not isinstance(output, (dict, list)):
            return ["structured_json output must be a JSON-serializable dict or list"]
        try:
            json.dumps(output)
        except (TypeError, ValueError):
            return ["structured_json output must be a JSON-serializable dict or list"]
        return []
