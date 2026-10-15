"""Grounded-synthesis plan allowlist and proposal model (ADR-008 Commit 9).

A synthesis engine may let a model propose a *structured plan* it will then
execute, but per the AETHER Multi-Model Intelligence Harness rule the model may
propose ONLY allowlisted structured plans -- never arbitrary tool calls.  This
module owns that gate:

* :data:`ALLOWED_PLAN_KINDS` -- the five structured plan kinds a model may
  propose (``classify``, ``summarize``, ``recommend``, ``extract``,
  ``decide``).
* :class:`PlanProposal` -- the frozen, fail-closed proposal model.  An
  unallowlisted ``plan_kind`` raises :class:`PlanNotAllowlisted`; a
  ``target_schema`` that is a URL (contains ``://``) or a ``rationale`` /
  ``target_schema`` carrying a secret marker raises :class:`PlanUnsafe`.
* :class:`PlanRegistry` -- a small registry mapping each plan kind to its
  description and structured-output schema name.

``PlanNotAllowlisted`` answers "the model proposed something it may not
propose"; ``PlanUnsafe`` answers "the content is structurally dangerous"
(secrets, arbitrary fetch targets).  The two are deliberately distinct so the
control plane can treat policy violations and injection attempts differently.

This module is self-contained: it imports nothing from the rest of the
``synthesis`` package so sibling Commit-9 modules can be developed in
parallel.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, field_validator

#: The only structured plan kinds a model may propose.
ALLOWED_PLAN_KINDS: tuple[str, ...] = (
    "classify",
    "summarize",
    "recommend",
    "extract",
    "decide",
)

#: Substring markers that must never appear in model-authored proposal content.
#: They match the canonical marker set used by the other leak guards (context
#: evidence, synthesis models, verification ``LEAK_MARKERS``) — common provider
#: secret/credential prefixes, PEM blocks, auth headers, password/secret/key
#: assignments, and JWT-shaped blobs — so the gate fails closed before a
#: proposal could be persisted or executed. Values are matched
#: case-insensitively (see ``_reject_secret_markers``), so "SK-", "akia",
#: "bearer " etc. all trip the gate just as they do in the context and
#: verification leak guards.
_SECRET_MARKERS: tuple[str, ...] = (
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


class PlanNotAllowlisted(Exception):
    """A model proposed a structured plan kind that is not on the allowlist."""


class PlanUnsafe(Exception):
    """A proposal field carries a secret marker or an arbitrary fetch target."""


class PlanProposal(BaseModel):
    """A structured plan a model proposes to execute.

    Frozen and ``extra="forbid"`` so a proposal is immutable once created and
    cannot smuggle arbitrary tool definitions alongside the plan.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_kind: str
    target_schema: str | None = None  # structured-output schema name, never a URL
    rationale: str = ""  # free text; must not carry secret markers

    @field_validator("plan_kind")
    @classmethod
    def _validate_plan_kind(cls, value: str) -> str:
        if value not in ALLOWED_PLAN_KINDS:
            raise PlanNotAllowlisted(
                f"plan_kind {value!r} is not on the allowlist ({', '.join(ALLOWED_PLAN_KINDS)})"
            )
        return value

    @field_validator("target_schema")
    @classmethod
    def _validate_target_schema(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "://" in value:
            raise PlanUnsafe(f"target_schema must name a schema, not a URL: {value!r}")
        _reject_secret_markers("target_schema", value)
        return value

    @field_validator("rationale")
    @classmethod
    def _validate_rationale(cls, value: str) -> str:
        _reject_secret_markers("rationale", value)
        return value


def _reject_secret_markers(field_name: str, value: str) -> None:
    """Raise ``PlanUnsafe`` when ``value`` carries any secret marker.

    Matching is case-insensitive (both the value and each marker are
    casefolded), mirroring the context and verification leak guards. Without
    normalization, case variants such as ``SK-...``, ``akia...``, or
    ``bearer ...`` would bypass the module's security contract.
    """
    lowered = value.casefold()
    for marker in _SECRET_MARKERS:
        if marker.casefold() in lowered:
            raise PlanUnsafe(
                f"{field_name} contains a secret marker {marker!r} and is "
                "not permitted in a plan proposal"
            )


_DEFAULT_PLAN_DEFINITIONS: dict[str, dict[str, str]] = {
    "classify": {
        "description": "Assign an item to one of a fixed, predeclared set of categories.",
        "output_schema": "classification",
    },
    "summarize": {
        "description": "Produce a concise, grounded summary of a source document.",
        "output_schema": "summary",
    },
    "recommend": {
        "description": "Propose ranked actions drawn from a fixed candidate set.",
        "output_schema": "recommendation",
    },
    "extract": {
        "description": "Pull declared structured fields out of an unstructured source.",
        "output_schema": "extraction",
    },
    "decide": {
        "description": "Choose a single outcome from an explicit decision table.",
        "output_schema": "decision",
    },
}


class PlanRegistry:
    """A registry of allowlisted plan kinds to their metadata.

    The registry is the reference the synthesis engine consults before it
    executes a :class:`PlanProposal`; an unknown kind must fail closed via
    :meth:`require` rather than being silently ignored.
    """

    def __init__(self, definitions: Mapping[str, Mapping[str, str]] | None = None) -> None:
        # Copy the mapping so callers cannot mutate registry state through the
        # mapping they supplied.
        self._definitions: dict[str, dict[str, str]] = (
            {kind: dict(defn) for kind, defn in definitions.items()}
            if definitions is not None
            else {}
        )

    def get(self, plan_kind: str) -> dict | None:
        """Return a copy of the definition for ``plan_kind`` or ``None``."""
        definition = self._definitions.get(plan_kind)
        return dict(definition) if definition is not None else None

    def require(self, plan_kind: str) -> dict:
        """Return the definition for ``plan_kind``, failing closed otherwise.

        Raises:
            PlanNotAllowlisted: when ``plan_kind`` is not registered.
        """
        definition = self.get(plan_kind)
        if definition is None:
            raise PlanNotAllowlisted(f"plan_kind {plan_kind!r} is not a registered plan")
        return definition

    @classmethod
    def default(cls) -> PlanRegistry:
        """Build the registry seeded with all five allowlisted plan kinds."""
        return cls(_DEFAULT_PLAN_DEFINITIONS)


__all__ = [
    "ALLOWED_PLAN_KINDS",
    "PlanNotAllowlisted",
    "PlanProposal",
    "PlanRegistry",
    "PlanUnsafe",
]
