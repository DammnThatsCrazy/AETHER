"""Contradiction/Veto Engine — evaluates all hard vetoes (blueprint §8.3).

Hard vetoes always block auto-merge regardless of confidence score.
A high score cannot override a hard veto.
"""

from __future__ import annotations

from typing import Optional

from .models import (
    ConfidenceBand,
    ConfidenceTier,
    DecisionType,
    EntityType,
    IdentityVeto,
    VetoType,
)


# Role/shared email patterns that indicate a shared inbox, not a personal email
SHARED_INBOX_PATTERNS = frozenset([
    "support@", "info@", "hello@", "contact@", "team@", "sales@",
    "help@", "admin@", "office@", "enquiries@", "customer@", "clients@",
    "family@", "shared@", "marketing@", "noreply@", "no-reply@",
])


async def evaluate_vetoes(
    tenant_id: str,
    candidate_tenant_id: Optional[str],
    candidate_entity_types: list[str],
    candidate_statuses: list[str],
    candidate_verified_emails: list[tuple[str, str]],  # (email, entity_id)
    candidate_authenticated_user_ids: list[tuple[str, str]],  # (user_id, entity_id)
    candidate_device_ids: list[str],
    candidate_has_revoked_consent: bool,
    candidate_is_deleted: bool,
    candidate_is_suppressed: bool,
    candidate_source_namespaces: list[str],
    current_entity_type: Optional[str] = None,
    current_device_ids: list[str] = None,
    current_verified_emails: list[str] = None,
    current_authenticated_user_ids: list[str] = None,
    manual_do_not_merge: bool = False,
    simultaneous_sessions: bool = False,
) -> list[IdentityVeto]:
    """Evaluate all hard vetoes. Returns list of vetoes (empty = no vetoes)."""
    vetoes: list[IdentityVeto] = []

    if current_device_ids is None:
        current_device_ids = []
    if current_verified_emails is None:
        current_verified_emails = []
    if current_authenticated_user_ids is None:
        current_authenticated_user_ids = []

    # 1. Cross-tenant candidate
    if candidate_tenant_id and candidate_tenant_id != tenant_id:
        vetoes.append(IdentityVeto(
            veto_type=VetoType.CROSS_TENANT,
            reason=f"Cross-tenant candidate: {candidate_tenant_id} != {tenant_id}",
            severity="blocked",
            details={"candidate_tenant": candidate_tenant_id, "current_tenant": tenant_id},
        ))

    # 2. Deleted/suppressed identity
    if candidate_is_deleted or candidate_is_suppressed:
        vetoes.append(IdentityVeto(
            veto_type=VetoType.DELETED_SUPPRESSED_IDENTITY,
            reason="Candidate identity is deleted or suppressed",
            severity="blocked",
            details={"deleted": candidate_is_deleted, "suppressed": candidate_is_suppressed},
        ))

    # 3. Revoked consent grant
    if candidate_has_revoked_consent:
        vetoes.append(IdentityVeto(
            veto_type=VetoType.REVOKED_CONSENT,
            reason="Candidate has revoked consent grant",
            severity="blocked",
            details={},
        ))

    # 4. Entity type mismatch
    if current_entity_type and candidate_entity_types:
        incompatible_pairs = [
            ("person", "agent"),
            ("agent", "person"),
            ("person", "account"),
            ("account", "person"),
            ("device", "person"),
            ("person", "device"),
            ("device", "agent"),
            ("agent", "device"),
        ]
        for cand_type in candidate_entity_types:
            for curr_type in ([current_entity_type] if current_entity_type else []):
                if (curr_type, cand_type) in incompatible_pairs:
                    vetoes.append(IdentityVeto(
                        veto_type=VetoType.ENTITY_TYPE_MISMATCH,
                        reason=f"Entity type mismatch: {curr_type} != {cand_type}",
                        severity="blocked",
                        details={"current_type": curr_type, "candidate_type": cand_type},
                    ))

    # 5. Agent/person merge attempt
    for cand_type in candidate_entity_types:
        if cand_type == "agent" and current_entity_type == "person":
            vetoes.append(IdentityVeto(
                veto_type=VetoType.AGENT_PERSON_MERGE_ATTEMPT,
                reason="Agent cannot merge into person — relationship edge only",
                severity="blocked",
                details={"current": current_entity_type, "candidate": cand_type},
            ))
        if cand_type == "person" and current_entity_type == "agent":
            vetoes.append(IdentityVeto(
                veto_type=VetoType.AGENT_PERSON_MERGE_ATTEMPT,
                reason="Person cannot merge into agent — relationship edge only",
                severity="blocked",
                details={"current": current_entity_type, "candidate": cand_type},
            ))

    # 6. Account/person merge attempt
    for cand_type in candidate_entity_types:
        if cand_type == "account" and current_entity_type == "person":
            vetoes.append(IdentityVeto(
                veto_type=VetoType.ACCOUNT_PERSON_MERGE_ATTEMPT,
                reason="Account cannot merge into person — relationship edge only",
                severity="blocked",
                details={"current": current_entity_type, "candidate": cand_type},
            ))

    # 7. Conflicting verified emails
    for cand_email, cand_entity_id in candidate_verified_emails:
        for curr_email in current_verified_emails:
            if cand_email == curr_email:
                vetoes.append(IdentityVeto(
                    veto_type=VetoType.CONFLICTING_VERIFIED_EMAIL,
                    reason=f"Conflicting verified email: {cand_email} on both entities",
                    severity="blocked",
                    details={
                        "email": cand_email,
                        "candidate_entity": cand_entity_id,
                        "current_entity": "current",
                    },
                ))

    # 8. Conflicting authenticated user IDs
    for cand_user_id, cand_entity_id in candidate_authenticated_user_ids:
        for curr_user_id in current_authenticated_user_ids:
            if cand_user_id == curr_user_id:
                vetoes.append(IdentityVeto(
                    veto_type=VetoType.CONFLICTING_AUTHENTICATED_USER,
                    reason=f"Conflicting authenticated user ID: {cand_user_id}",
                    severity="blocked",
                    details={
                        "user_id": cand_user_id,
                        "candidate_entity": cand_entity_id,
                    },
                ))

    # 9. Known shared device
    for cand_device in candidate_device_ids:
        for curr_device in current_device_ids:
            if cand_device == curr_device:
                vetoes.append(IdentityVeto(
                    veto_type=VetoType.SHARED_DEVICE,
                    reason=f"Shared device detected: {cand_device}",
                    severity="medium",
                    details={"device_id": cand_device},
                ))

    # 10. Known shared inbox
    for cand_email, _ in candidate_verified_emails:
        for pattern in SHARED_INBOX_PATTERNS:
            if cand_email.startswith(pattern):
                vetoes.append(IdentityVeto(
                    veto_type=VetoType.SHARED_INBOX,
                    reason=f"Shared inbox pattern detected: {cand_email}",
                    severity="medium",
                    details={"email": cand_email, "pattern": pattern},
                ))

    # 11. Provider namespace collision
    if len(candidate_source_namespaces) > 1:
        seen_namespaces: set[str] = set()
        for ns in candidate_source_namespaces:
            if ns in seen_namespaces:
                vetoes.append(IdentityVeto(
                    veto_type=VetoType.PROVIDER_NAMESPACE_COLLISION,
                    reason=f"Provider namespace collision: {ns}",
                    severity="blocked",
                    details={"namespace": ns},
                ))
            seen_namespaces.add(ns)

    # 12. Simultaneous contradictory sessions
    if simultaneous_sessions:
        vetoes.append(IdentityVeto(
            veto_type=VetoType.SIMULTANEOUS_CONTRADICTORY_SESSIONS,
            reason="Simultaneous contradictory sessions detected",
            severity="blocked",
            details={},
        ))

    # 13. Manual do-not-merge flag
    if manual_do_not_merge:
        vetoes.append(IdentityVeto(
            veto_type=VetoType.MANUAL_DO_NOT_MERGE,
            reason="Manual do-not-merge flag set",
            severity="blocked",
            details={},
        ))

    return vetoes


def has_any_veto(vetoes: list[IdentityVeto]) -> bool:
    """Check if any veto is present (any veto blocks auto-merge)."""
    return len(vetoes) > 0


def get_confidence_band(
    score: float,
    tier: ConfidenceTier,
    vetoes: list[IdentityVeto],
) -> ConfidenceBand:
    """Map score + tier + vetoes to confidence band (blueprint §8.2).

    A high score cannot override a hard veto.
    """
    if has_any_veto(vetoes):
        return ConfidenceBand.BLOCKED

    if score >= 0.97:
        return ConfidenceBand.VERY_HIGH
    elif score >= 0.90:
        return ConfidenceBand.HIGH
    elif score >= 0.70:
        return ConfidenceBand.MEDIUM
    elif score >= 0.30:
        return ConfidenceBand.LOW
    else:
        return ConfidenceBand.BLOCKED
