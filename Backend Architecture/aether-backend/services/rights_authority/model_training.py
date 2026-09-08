"""Aether — Rights Authority: training-manifest VERIFICATION adapter.

Stream P-B2 add-on over ``services.rights_authority.model_governance`` (blueprint
§8 / §38–§40). A candidate training request that references a
:class:`~services.rights_authority.model_governance.TrainingDataManifest` must
clear BOTH existing gates before training material may be consumed:

1. ``model_governance.validate_training_manifest`` — every dataset artifact must
   be backed by an allowed, training-use ``RightsDecision`` in the decision store;
2. ``model_governance.model_training_eligibility`` — the governing grant(s) must
   authorise the requested learning class.

When either gate blocks, the block is made **durable + surfaced**: a ``pending``
``model_training_input`` :class:`~services.rights_authority.impact.RightsImpactItem`
is enqueued through the existing impact machinery, so the blocked request is
visible in the pending-remediation surface (e.g. Kyber) and never silently
dropped. No training input is ever implied to have been consumed.

This module calls the existing governance functions with their EXACT signatures
and semantics; it adds no parallel eligibility logic.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from shared.logger.logger import get_logger
from services.rights_authority.impact import RightsImpactItem, persist_impact_items
from services.rights_authority.model_governance import (
    CONTRIBUTED_MODEL_TRAINING,
    LearningEligibilityReport,
    TrainingDataManifest,
    model_training_eligibility,
    validate_training_manifest,
)

logger = get_logger("aether.rights_irrl.model_training")

POLICY_VERSION = "irrl-2"

# Required-action token on the durable pending impact item for a blocked request.
# A blocked request consumed NO training input, so retrain/evaluation is never
# implied; the pending item asks for the eligibility block to be resolved.
TRAINING_BLOCK_ACTION = "eligibility_resolution_required"
TRAINING_BLOCK_COMPONENT_TYPE = "model_training_input"


class TrainingManifestVerification(BaseModel):
    """Honest result of verifying one candidate training request."""

    tenant_id: str
    run_id: str
    model_ref: str = ""
    learning_class: str = CONTRIBUTED_MODEL_TRAINING
    eligible: bool = False
    blocked: bool = True
    denial_reason_codes: list[str] = Field(default_factory=list)
    manifest_eligible: bool = False
    eligibility_eligible: bool = False
    manifest_report: Optional[dict[str, Any]] = None
    eligibility_report: Optional[dict[str, Any]] = None
    pending_impact: Optional[RightsImpactItem] = None
    impact_ids: list[str] = Field(default_factory=list)
    persisted: bool = False


def _report_dict(report: LearningEligibilityReport) -> dict[str, Any]:
    return report.model_dump(mode="json")


async def evaluate_training_manifest(
    *,
    manifest: TrainingDataManifest,
    tenant_id: str,
    source_id: str = "",
    learning_class: str = CONTRIBUTED_MODEL_TRAINING,
    grants: Optional[list[Any]] = None,
    decision_repository: Optional[Any] = None,
    artifact_ref: Optional[str] = None,
    grant_id: Optional[str] = None,
) -> TrainingManifestVerification:
    """Run both training gates for a candidate manifest (no persistence).

    Returns a :class:`TrainingManifestVerification`. When blocked, it carries the
    pending ``model_training_input`` impact item on ``pending_impact`` so the
    caller can persist/surface it; when eligible, no impact item is fabricated.
    """
    manifest_report = await validate_training_manifest(
        manifest,
        decision_repository=decision_repository,
    )
    eligibility_report = await model_training_eligibility(
        tenant_id,
        source_id=source_id,
        learning_class=learning_class,
        artifact_ref=artifact_ref or _first_dataset_ref(manifest),
        grants=grants,
        manifest_refs=[manifest.run_id],
    )

    deny_codes = sorted(set(
        (manifest_report.denial_reason_codes or [])
        + (eligibility_report.denial_reason_codes or [])
    ))
    eligible = bool(manifest_report.eligible and eligibility_report.eligible)

    verification = TrainingManifestVerification(
        tenant_id=tenant_id,
        run_id=manifest.run_id,
        model_ref=manifest.model_ref,
        learning_class=_learning_class_value(learning_class),
        eligible=eligible,
        blocked=not eligible,
        denial_reason_codes=deny_codes,
        manifest_eligible=bool(manifest_report.eligible),
        eligibility_eligible=bool(eligibility_report.eligible),
        manifest_report=_report_dict(manifest_report),
        eligibility_report=_report_dict(eligibility_report),
    )

    if eligible:
        return verification

    verification.pending_impact = _block_item(
        verification=verification,
        manifest=manifest,
        grant_id=grant_id,
        artifact_ref=artifact_ref or _first_dataset_ref(manifest) or manifest.run_id,
    )
    return verification


def _first_dataset_ref(manifest: TrainingDataManifest) -> Optional[str]:
    refs = manifest.dataset_artifact_refs or []
    return refs[0] if refs else None


def _learning_class_value(learning_class: Any) -> str:
    if hasattr(learning_class, "value"):
        return str(learning_class.value)
    return str(learning_class or CONTRIBUTED_MODEL_TRAINING).strip().lower()


def _block_item(
    *,
    verification: TrainingManifestVerification,
    manifest: TrainingDataManifest,
    grant_id: Optional[str],
    artifact_ref: str,
) -> RightsImpactItem:
    codes = ", ".join(verification.denial_reason_codes or ["unknown_denial"])
    return RightsImpactItem(
        tenant_id=verification.tenant_id,
        grant_id=grant_id,
        artifact_ref=artifact_ref,
        component_type=TRAINING_BLOCK_COMPONENT_TYPE,  # type: ignore[arg-type]
        required_action=TRAINING_BLOCK_ACTION,
        remediation_state="pending",
        reason=(
            f"training manifest {verification.run_id} (model "
            f"{verification.model_ref or '?'}) blocked for tenant "
            f"{verification.tenant_id}: {codes} — no training input consumed; "
            f"pending eligibility resolution"
        ),
        evidence_refs=[f"manifest:{manifest.run_id}", *manifest.rights_decision_refs],
    )


async def verify_training_request(
    *,
    manifest: TrainingDataManifest,
    tenant_id: str,
    source_id: str = "",
    learning_class: str = CONTRIBUTED_MODEL_TRAINING,
    grants: Optional[list[Any]] = None,
    decision_repository: Optional[Any] = None,
    artifact_ref: Optional[str] = None,
    grant_id: Optional[str] = None,
    persist_block: bool = True,
) -> TrainingManifestVerification:
    """Verify a candidate training request and (by default) durably record blocks.

    Delegates to :func:`evaluate_training_manifest` and, when the request is
    blocked and ``persist_block`` is true, persists the pending
    ``model_training_input`` impact item through
    ``services.rights_authority.impact.persist_impact_items`` so the block is
    durable + surfaced. Nothing is executed; the block remains ``pending`` until
    an operator/adapter resolves eligibility.
    """
    verification = await evaluate_training_manifest(
        manifest=manifest,
        tenant_id=tenant_id,
        source_id=source_id,
        learning_class=learning_class,
        grants=grants,
        decision_repository=decision_repository,
        artifact_ref=artifact_ref,
        grant_id=grant_id,
    )
    if verification.pending_impact is None or not persist_block:
        return verification
    verification.impact_ids = await persist_impact_items([verification.pending_impact])
    verification.persisted = True
    return verification


__all__ = [
    "POLICY_VERSION",
    "TRAINING_BLOCK_ACTION",
    "TRAINING_BLOCK_COMPONENT_TYPE",
    "TrainingManifestVerification",
    "evaluate_training_manifest",
    "verify_training_request",
]
