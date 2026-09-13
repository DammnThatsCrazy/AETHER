"""Reconciled Control Plane — schema/mapping drift automation (Phase 3).

The §25 → §8.1 → §38 pipeline in engine form: deterministic canonical schema
fingerprints replace placeholder/version-derived schema indicators (§25), the
§8.1 confidence policy turns candidate mappings into review states (candidates
are epistemic proposals, never truth — §18), and automatic promotion is
recorded only when every §38 gate holds (fail closed).

* ``canonical_schema_fingerprint`` / ``schema_fingerprint_status`` /
  ``is_drifted`` — §25. Fingerprint inputs are restricted to exactly
  ``FINGERPRINT_INPUTS``; an unknown key raises (§25 scope drift is a
  fingerprint-meaning change, never silent). Missing optional components are
  absent-by-absence — never defaulted — while the §25 required set
  (``event_registry``, ``field_definitions``) must be present. Invariant: the
  release artifact fingerprint = the runtime-reported fingerprint = the
  compatible desired-state fingerprint; any mismatch is classified drift.
* ``review_state_for`` / ``record_candidate`` — §8.1/§18. Confidence policy:
  >=0.98 auto-propose only; 0.80–0.979 review recommended; <0.80 unresolved.
  Sensitive mappings still require authorization regardless of confidence
  (never ``auto_propose``).
* ``evaluate_auto_promotion`` / ``auto_promote_decision`` — §38. Automatic
  promotion is allowed only when ALL of the eight §38 gates hold; any missing
  gate is a failed gate and an unknown gate key raises (§38 — never silently
  ignored). A promoted run records its verdict; a non-promoted run carries the
  ``action_required_ref`` that routes the review/action.

Phase-3 boundary (unchanged from the program boundary): auto-promotion here
records a *decision* — nothing in this module executes a change. Execution
rides the Phase-1/2 governed path (ChangeSet → §34 executor) which owns risk
authority and approvals; CP-03 ("discovery never equals authorization") and
CP-04 ("capability never equals enablement") hold — mapping candidates and
promotion verdicts are evidence for that path, never an instruction to it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from services.managed_integrations.contracts import (
    SCHEMA_MAPPING_AUTO_PROMOTE_GATES,
    is_schema_mapping_auto_promote_gate,
)
from services.managed_integrations.schema_mapping_repository import (
    MappingCandidateRow,
    SchemaMappingRunRow,
    get_mapping_candidate_repository,
    get_schema_mapping_run_repository,
)

# §25 fingerprint inputs — the ONLY components a canonical fingerprint may
# incorporate. Keeping this tuple exact prevents fingerprint-scope drift:
# adding a component changes every fingerprint's meaning, which is a §25
# invariant change, not a routine edit.
FINGERPRINT_INPUTS: tuple[str, ...] = (
    "event_registry",
    "field_definitions",
    "required_optional_state",
    "enums",
    "event_family_bindings",
    "consent_purpose_bindings",
    "contract_versions",
    "extension_registry",
    "mapping_contract_version",
)

# §25: without the event registry and field definitions there is nothing to
# fingerprint — the required set must be present on every call.
_REQUIRED_FINGERPRINT_INPUTS = frozenset({"event_registry", "field_definitions"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── §25 deterministic canonical schema fingerprints ──────────────────────────


def canonical_schema_fingerprint(components: dict[str, Any]) -> str:
    """Deterministic §25 canonical schema fingerprint for ``components``.

    Canonicalization: accept only keys in ``FINGERPRINT_INPUTS`` (unknown keys
    raise — §25 fingerprint-scope drift is rejected, never silently absorbed),
    require the §25 ``event_registry`` + ``field_definitions`` pair, sort the
    keys, and ``json.dumps`` with ``sort_keys=True`` and compact separators so
    insertion order can never change the digest. Missing optional components
    are fine: absent = absent (never defaulted — a defaulted component would
    manufacture fingerprint content the schema does not have). Returns the
    sha256 hex digest of the canonical serialization.
    """
    unknown = sorted(set(components) - set(FINGERPRINT_INPUTS))
    if unknown:
        raise ValueError(
            f"unknown §25 fingerprint component(s) {unknown} — inputs are "
            f"exactly {list(FINGERPRINT_INPUTS)}; adding a component changes "
            "every fingerprint's meaning"
        )
    missing = sorted(_REQUIRED_FINGERPRINT_INPUTS - set(components))
    if missing:
        raise ValueError(
            "missing required §25 fingerprint component(s) "
            f"{missing} (event_registry + field_definitions must be present)"
        )
    canonical = json.dumps(
        components, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def schema_fingerprint_status(
    release: Optional[str],
    runtime: Optional[str],
    desired: Optional[str],
) -> dict[str, bool]:
    """Pairwise §25 fingerprint comparison across the three authorities.

    Present-vs-missing compares as a mismatch: ``None`` never equals a
    fingerprint (an authority that did not report one cannot be said to
    agree). Returns ``release_runtime_match`` / ``runtime_desired_match`` /
    ``release_desired_match``.
    """
    return {
        "release_runtime_match": (
            release is not None and runtime is not None and release == runtime
        ),
        "runtime_desired_match": (
            runtime is not None and desired is not None and runtime == desired
        ),
        "release_desired_match": (
            release is not None and desired is not None and release == desired
        ),
    }


def is_drifted(
    release: Optional[str],
    runtime: Optional[str],
    desired: Optional[str],
) -> bool:
    """§25 drift classifier: drifted unless all three fingerprints are equal.

    ``True`` unless every authority reported a fingerprint AND all three are
    identical — a missing fingerprint is drift (the invariant release =
    runtime = desired cannot be checked, so the schema is classified drifted
    rather than assumed healthy).
    """
    return not (
        release is not None
        and runtime is not None
        and desired is not None
        and release == runtime == desired
    )


# ── §8.1 review-state policy ─────────────────────────────────────────────────


def review_state_for(confidence: float, sensitivity_class: Optional[str]) -> str:
    """Map (§8.1 confidence, sensitivity) to a §8.1 review state.

    §8.1 confidence policy: >=0.98 auto-propose only; 0.80–0.979 review
    recommended; <0.80 unresolved. The §8.1 sensitive override dominates:
    sensitive mappings always require authorization regardless of confidence,
    so a sensitive candidate can reach at most ``review`` (>=0.80) and never
    ``auto_propose``.

    Boundary semantics are exact: the auto-propose band starts at 0.98
    (inclusive) and the review band is [0.80, 0.98).
    """
    if sensitivity_class is not None:
        return "review" if confidence >= 0.80 else "unresolved"
    if confidence >= 0.98:
        return "auto_propose"
    if confidence >= 0.80:
        return "review"
    return "unresolved"


async def record_candidate(**fields: Any) -> dict:
    """Persist one §8.1 semantic-mapping candidate (via the repository).

    ``fields`` mirror ``MappingCandidateRow`` (candidate_id, source_ref,
    source_path, canonical_target, mapping_method, confidence, rationale,
    sensitivity_class, transform_ref, tenant_id, environment_id). When
    ``review_state`` is omitted it is computed from confidence +
    sensitivity_class via ``review_state_for`` (§8.1); ``created_at`` defaults
    to now. The candidate is an epistemic proposal (§18), never truth.
    """
    if fields.get("review_state") is None:
        fields["review_state"] = review_state_for(
            fields["confidence"], fields.get("sensitivity_class")
        )
    created_at = fields.pop("created_at", None)
    fields["created_at"] = created_at or _now()
    repo = get_mapping_candidate_repository()
    return await repo.create(MappingCandidateRow(**fields))


# ── §38 auto-promotion gates ─────────────────────────────────────────────────


def _check_gate_keys(gates: dict[str, bool]) -> None:
    """Reject any gate key outside the §38 set (never silently ignored)."""
    unknown = sorted(
        key for key in gates if not is_schema_mapping_auto_promote_gate(key)
    )
    if unknown:
        raise ValueError(
            f"unknown §38 auto-promotion gate key(s) {unknown} — gates are "
            f"exactly {list(SCHEMA_MAPPING_AUTO_PROMOTE_GATES)}; an "
            "unrecognized gate must never be silently ignored"
        )


def auto_promote_decision(gates: dict[str, bool]) -> str:
    """Classify a §38 gate verdict as promote | review_required | action_required.

    * ``promote`` — every §38 gate holds (missing gates count as false, so a
      7-gate or partial verdict can never promote — fail closed).
    * ``review_required`` — the failed gate is ``high_confidence``: the §8.1
      confidence policy wants a human review of the mapping itself.
    * ``action_required`` — high confidence held but some other §38 gate
      failed (new data category / sensitive field / processing purpose /
      platform permission / semantic loss / shadow / health): per §38
      "otherwise generate a review/action", the run routes to an action
      rather than promoting.
    """
    _check_gate_keys(gates)
    if all(gates.get(key, False) for key in SCHEMA_MAPPING_AUTO_PROMOTE_GATES):
        return "promote"
    if not gates.get("high_confidence", False):
        return "review_required"
    return "action_required"


async def evaluate_auto_promotion(
    *,
    tenant_id: str,
    environment_id: str,
    managed_integration_ref: str,
    gates: dict[str, bool],
    candidates: list[str],
    observed_fingerprint: Optional[str],
    desired_fingerprint: Optional[str],
    run_id: Optional[str] = None,
    diff_summary: Optional[dict[str, Any]] = None,
    action_required_ref: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Run one §38 evaluation and persist the verdict as a run row.

    Gate keys must be a subset of ``SCHEMA_MAPPING_AUTO_PROMOTE_GATES`` — an
    unknown key raises (§38, never silently ignored). ``promoted`` is true
    only when all eight gates are present AND true; any missing gate is a
    failed gate (fail closed), so a 7-gate verdict can never promote even when
    every supplied gate is true.

    The persisted row carries the §25 observed/desired fingerprints that were
    compared, the diff summary, the candidate ids considered, the per-gate
    verdicts, and the ``action_required_ref`` when the run did not promote.
    Promotion records a decision only — executing the change rides the
    Phase-1/2 governed path (CP-03/CP-04).
    """
    _check_gate_keys(gates)
    promoted = len(gates) == len(SCHEMA_MAPPING_AUTO_PROMOTE_GATES) and all(
        gates[key] is True for key in SCHEMA_MAPPING_AUTO_PROMOTE_GATES
    )
    row = SchemaMappingRunRow(
        run_id=run_id or f"smrun_{uuid.uuid4().hex}",
        managed_integration_ref=managed_integration_ref,
        tenant_id=tenant_id,
        environment_id=environment_id,
        observed_schema_fingerprint=observed_fingerprint,
        desired_schema_fingerprint=desired_fingerprint,
        diff_summary=dict(diff_summary) if diff_summary is not None else {},
        candidate_ids=list(candidates),
        gate_results=dict(gates),
        promoted=promoted,
        action_required_ref=action_required_ref,
        created_at=now or _now(),
    )
    repo = get_schema_mapping_run_repository()
    return await repo.create(row)
