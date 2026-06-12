"""Identity Resolution Service — the canonical entry point.

Flow for each canonical event:
    1. Extract identity signals from event.
    2. Normalize signals.
    3. Hash sensitive values.
    4. Persist signal observations.
    5. Look up existing aliases/entities for this tenant.
    6. Score candidate matches.
    7. Apply merge policy.
    8. Create new canonical entity if needed.
    9. Link aliases if allowed.
    10. Merge entities if allowed.
    11. Create candidate/conflict if ambiguous.
    12. Write approved graph edges.
    13. Emit audit record.
    14. Emit metrics.
    15. Return decision response.

Idempotency: same event processed twice must not duplicate aliases,
graph edges, or merge records. The repository layer enforces this.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from .audit import IdentityAuditWriter
from .conflicts import IdentityConflictManager
from .exceptions import CrossTenantError, IdentityError
from .graph_writer import IdentityGraphWriter
from .hashing import (
    hash_email,
    hash_external_id,
    hash_fingerprint,
    hash_phone,
    hash_wallet,
    redact_display,
)
from .merge_policy import MergePolicyContext, evaluate, evaluate_operator_merge
from .metrics import IdentityMetrics
from .models import (
    ConfidenceTier,
    EdgeType,
    EntityType,
    IdentityResolutionDecision,
    IdentitySignalType,
    MergeDecision,
    REASON_NEW_ENTITY,
)
from .repository import IdentityResolutionRepository
from .signals import extract_signals
from .split_policy import SplitPolicyContext, evaluate_split

logger = get_logger("aether.identity.resolver")

# Signals that must be hashed before persistence
_HASH_ON_INGEST: dict[IdentitySignalType, str] = {
    IdentitySignalType.EMAIL_HASH: "email",
    IdentitySignalType.PHONE_HASH: "phone",
    IdentitySignalType.DEVICE_FINGERPRINT: "fingerprint",
}

# Signals that are attribution-only (never trigger identity merge)
_ATTRIBUTION_ONLY: frozenset[IdentitySignalType] = frozenset({
    IdentitySignalType.CAMPAIGN_ID,
    IdentitySignalType.JOURNEY_ID,
})


class IdentityResolutionService:
    """
    Orchestrates the full identity resolution pipeline for a single event
    or a direct operator action.
    """

    def __init__(
        self,
        repo: IdentityResolutionRepository,
        graph_writer: IdentityGraphWriter,
        audit_writer: IdentityAuditWriter,
        conflict_manager: IdentityConflictManager,
        metrics: IdentityMetrics,
    ) -> None:
        self._repo = repo
        self._graph = graph_writer
        self._audit = audit_writer
        self._conflicts = conflict_manager
        self._metrics = metrics

    # ── Main entry point ──────────────────────────────────────────────────

    async def resolve_event(
        self,
        event: dict[str, Any],
        tenant_id: str,
    ) -> IdentityResolutionDecision:
        """
        Resolve identity for a single canonical event payload.
        Returns the resolution decision (idempotent).
        """
        try:
            return await self._resolve_event_inner(event, tenant_id)
        except CrossTenantError:
            self._metrics.record_blocked("cross_tenant")
            raise
        except IdentityError as exc:
            logger.warning("Identity error during resolution: %s", exc)
            self._metrics.record_resolve(success=False, tenant_id=tenant_id)
            return IdentityResolutionDecision(
                tenant_id=tenant_id,
                canonical_entity_id="",
                decision=MergeDecision.BLOCKED,
                confidence=0.0,
                confidence_tier=ConfidenceTier.BLOCKED,
                reason_codes=[str(exc)],
                blocked_reason=str(exc),
            )
        except Exception as exc:
            logger.error("Unexpected identity resolution error: %s", exc, exc_info=True)
            self._metrics.record_resolve(success=False, tenant_id=tenant_id)
            return IdentityResolutionDecision(
                tenant_id=tenant_id,
                canonical_entity_id="",
                decision=MergeDecision.NOOP,
                confidence=0.0,
                confidence_tier=ConfidenceTier.BLOCKED,
                reason_codes=["internal_error"],
            )

    async def _resolve_event_inner(
        self, event: dict, tenant_id: str
    ) -> IdentityResolutionDecision:
        event_id = event.get("event_id", "")
        consent_snapshot = _extract_consent(event)

        # ── 1. Extract signals ────────────────────────────────────────────
        raw_signals = extract_signals(event, tenant_id)
        if not raw_signals:
            return IdentityResolutionDecision(
                tenant_id=tenant_id,
                canonical_entity_id="",
                decision=MergeDecision.NOOP,
                confidence=0.0,
                confidence_tier=ConfidenceTier.WEAK,
                reason_codes=["no_signals"],
            )

        # ── 2 & 3. Normalize + hash sensitive values ──────────────────────
        hashed_signals: list[tuple[IdentitySignalType, str, str]] = []
        # (type, hash, display_redacted)
        for sig in raw_signals:
            h, display = _hash_signal(sig.type, sig.value, tenant_id)
            if h:
                hashed_signals.append((sig.type, h, display))
                self._metrics.record_signal_observation(sig.type.value)

        # ── 4. Persist signal observations ────────────────────────────────
        for sig in raw_signals:
            h, display = _hash_signal(sig.type, sig.value, tenant_id)
            if h:
                await self._repo.create_signal_observation(
                    tenant_id=tenant_id,
                    source_event_id=event_id,
                    source_platform=sig.source_platform,
                    source_sdk=sig.source_sdk,
                    signal_type=sig.type,
                    signal_value_hash=h,
                    raw_value_redacted=display,
                    observed_at=sig.observed_at,
                    consent_snapshot=sig.consent_snapshot,
                    context={"source": sig.source},
                )

        # ── 5. Find existing aliases/entities for this tenant ─────────────
        existing_entity_ids: list[str] = []
        matching_types: list[IdentitySignalType] = []
        revoked_types: list[IdentitySignalType] = []

        for (sig_type, sig_hash, _) in hashed_signals:
            if sig_type in _ATTRIBUTION_ONLY:
                continue
            entity_ids = await self._repo.find_subjects_by_alias(
                tenant_id, sig_type, sig_hash
            )
            if entity_ids:
                matching_types.append(sig_type)
                for eid in entity_ids:
                    if eid not in existing_entity_ids:
                        existing_entity_ids.append(eid)

        # ── 6. Check for conflicting strong aliases ───────────────────────
        has_conflict = len(existing_entity_ids) > 1 and _has_strong_signal(matching_types)

        # ── 7. Apply merge policy ─────────────────────────────────────────
        policy_ctx = MergePolicyContext(
            tenant_id=tenant_id,
            source_tenant_id=tenant_id,
            matching_signal_types=matching_types,
            consent_snapshot=consent_snapshot,
            revoked_signal_types=revoked_types,
            has_conflict=has_conflict,
            existing_entity_ids=existing_entity_ids,
        )
        policy_result = evaluate(policy_ctx)

        # ── 8. Create or fetch canonical entity ───────────────────────────
        canonical_entity_id: str
        is_new = False

        if policy_result.decision == MergeDecision.CREATE or not existing_entity_ids:
            canonical_entity_id = str(uuid.uuid4())
            entity_type = _infer_entity_type(raw_signals)
            await self._repo.create_subject(
                tenant_id=tenant_id,
                canonical_entity_id=canonical_entity_id,
                entity_type=entity_type,
            )
            is_new = True
        elif policy_result.decision in (MergeDecision.MERGE, MergeDecision.LINK):
            canonical_entity_id = (
                policy_result.merge_target_entity_id or existing_entity_ids[0]
            )
        else:
            # CANDIDATE, REJECT, BLOCKED → use first existing or create anonymous
            canonical_entity_id = existing_entity_ids[0] if existing_entity_ids else str(uuid.uuid4())
            if not existing_entity_ids:
                is_new = True
                entity_type = _infer_entity_type(raw_signals)
                await self._repo.create_subject(
                    tenant_id=tenant_id,
                    canonical_entity_id=canonical_entity_id,
                    entity_type=entity_type,
                )

        # ── 9. Link aliases ───────────────────────────────────────────────
        linked_aliases: list[str] = []
        if policy_result.decision not in (MergeDecision.BLOCKED, MergeDecision.REJECT):
            for sig in raw_signals:
                h, display = _hash_signal(sig.type, sig.value, tenant_id)
                if not h or sig.type in _ATTRIBUTION_ONLY:
                    continue
                alias = await self._repo.upsert_alias(
                    tenant_id=tenant_id,
                    canonical_entity_id=canonical_entity_id,
                    alias_type=sig.type,
                    alias_value_hash=h,
                    alias_display_value_redacted=display,
                    source=sig.source,
                    source_event_id=event_id,
                    source_platform=sig.source_platform,
                    confidence=policy_result.confidence,
                    confidence_tier=policy_result.confidence_tier,
                    consent_snapshot=consent_snapshot,
                )
                linked_aliases.append(alias["id"])

        # ── 10. Merge entities if approved ───────────────────────────────
        merge_event_id: Optional[str] = None
        if policy_result.decision == MergeDecision.MERGE and policy_result.merge_target_entity_id:
            for from_id in existing_entity_ids:
                if from_id == canonical_entity_id:
                    continue
                merge_event_id = await self._audit.record_merge(
                    tenant_id=tenant_id,
                    from_entity_id=from_id,
                    into_entity_id=canonical_entity_id,
                    resulting_entity_id=canonical_entity_id,
                    confidence=policy_result.confidence,
                    confidence_tier=policy_result.confidence_tier,
                    reason_codes=policy_result.reason_codes,
                    source_event_ids=[event_id] if event_id else [],
                )
                await self._repo.mark_subject_merged(from_id, canonical_entity_id)
                self._metrics.record_merge(tenant_id=tenant_id)

        # ── 11. Create conflict if ambiguous ──────────────────────────────
        conflict_id: Optional[str] = None
        if policy_result.decision == MergeDecision.CANDIDATE and has_conflict:
            conflict_id = await self._conflicts.open_conflict(
                tenant_id=tenant_id,
                candidate_entity_ids=existing_entity_ids,
                candidate_aliases=[
                    {"type": st.value, "hash": h, "display": d}
                    for (st, h, d) in hashed_signals
                ],
                conflict_type=policy_result.conflict_type or "ambiguous_match",
                confidence=policy_result.confidence,
                reason_codes=policy_result.reason_codes,
            )
            self._metrics.record_conflict()

        # ── 12. Write graph edges ─────────────────────────────────────────
        decision_obj = IdentityResolutionDecision(
            tenant_id=tenant_id,
            canonical_entity_id=canonical_entity_id,
            decision=policy_result.decision,
            confidence=policy_result.confidence,
            confidence_tier=policy_result.confidence_tier,
            reason_codes=policy_result.reason_codes,
            linked_aliases=linked_aliases,
            candidate_entity_ids=[
                e for e in existing_entity_ids if e != canonical_entity_id
            ],
            conflict_id=conflict_id,
            source_event_ids=[event_id] if event_id else [],
            blocked_reason=(
                policy_result.reason_codes[0]
                if policy_result.decision == MergeDecision.BLOCKED
                else None
            ),
            is_new_entity=is_new,
        )

        graph_edges = await self._graph.write_decision(
            decision_obj, [event_id] if event_id else [], consent_snapshot
        )
        decision_obj.graph_edges_written = graph_edges

        # Write attribution / relationship edges
        await self._write_relationship_edges(
            raw_signals, canonical_entity_id, tenant_id,
            policy_result.confidence, policy_result.confidence_tier,
            policy_result.reason_codes, [event_id] if event_id else [],
            consent_snapshot,
        )

        # ── 13. Emit audit record ─────────────────────────────────────────
        audit_id = await self._audit.record_resolution(
            tenant_id=tenant_id,
            decision=policy_result.decision,
            canonical_entity_id=canonical_entity_id,
            candidate_entity_ids=existing_entity_ids,
            confidence=policy_result.confidence,
            confidence_tier=policy_result.confidence_tier,
            reason_codes=policy_result.reason_codes,
            source_event_ids=[event_id] if event_id else [],
            policy_result=policy_result.decision.value,
            consent_snapshot=consent_snapshot,
        )
        decision_obj.audit_id = audit_id

        # ── 14. Emit metrics ──────────────────────────────────────────────
        if policy_result.decision == MergeDecision.BLOCKED:
            blocked_reason = _blocked_reason_category(policy_result.reason_codes)
            self._metrics.record_blocked(blocked_reason)
        elif policy_result.decision == MergeDecision.CANDIDATE:
            self._metrics.record_candidate()
        elif policy_result.decision == MergeDecision.LINK:
            self._metrics.record_link(tenant_id)

        self._metrics.record_resolve(
            success=policy_result.decision != MergeDecision.BLOCKED,
            tenant_id=tenant_id,
        )

        return decision_obj

    # ── Operator actions ──────────────────────────────────────────────────

    async def operator_merge(
        self,
        tenant_id: str,
        primary_entity_id: str,
        secondary_entity_id: str,
        actor_id: str,
        actor_type: str = "operator",
        reason: str = "manual_merge",
    ) -> IdentityResolutionDecision:
        """Operator-initiated merge of two canonical entities."""
        policy = evaluate_operator_merge(
            tenant_id=tenant_id,
            primary_entity_id=primary_entity_id,
            secondary_entity_id=secondary_entity_id,
            actor_id=actor_id,
            actor_type=actor_type,
            reason=reason,
        )
        if policy.decision != MergeDecision.MERGE:
            return IdentityResolutionDecision(
                tenant_id=tenant_id,
                canonical_entity_id=primary_entity_id,
                decision=policy.decision,
                confidence=policy.confidence,
                confidence_tier=policy.confidence_tier,
                reason_codes=policy.reason_codes,
            )

        merge_event_id = await self._audit.record_merge(
            tenant_id=tenant_id,
            from_entity_id=secondary_entity_id,
            into_entity_id=primary_entity_id,
            resulting_entity_id=primary_entity_id,
            confidence=policy.confidence,
            confidence_tier=policy.confidence_tier,
            reason_codes=policy.reason_codes,
            source_event_ids=[],
            actor_type=actor_type,
            actor_id=actor_id,
        )
        await self._repo.mark_subject_merged(secondary_entity_id, primary_entity_id)
        self._metrics.record_merge(tenant_id=tenant_id)

        decision_obj = IdentityResolutionDecision(
            tenant_id=tenant_id,
            canonical_entity_id=primary_entity_id,
            decision=MergeDecision.MERGE,
            confidence=policy.confidence,
            confidence_tier=policy.confidence_tier,
            reason_codes=policy.reason_codes,
            candidate_entity_ids=[secondary_entity_id],
        )

        audit_id = await self._audit.record_resolution(
            tenant_id=tenant_id,
            decision=MergeDecision.MERGE,
            canonical_entity_id=primary_entity_id,
            candidate_entity_ids=[secondary_entity_id],
            confidence=policy.confidence,
            confidence_tier=policy.confidence_tier,
            reason_codes=policy.reason_codes,
            source_event_ids=[],
            policy_result="operator_merge",
        )
        decision_obj.audit_id = audit_id

        graph_edges = await self._graph.write_decision(decision_obj, [], None)
        decision_obj.graph_edges_written = graph_edges

        return decision_obj

    async def operator_split(
        self,
        tenant_id: str,
        original_entity_id: str,
        actor_id: str,
        actor_type: str = "operator",
        reason: str = "incorrect_merge",
        source_merge_event_id: Optional[str] = None,
    ) -> dict:
        """Operator-initiated split of an incorrectly merged entity."""
        split_ctx = SplitPolicyContext(
            tenant_id=tenant_id,
            original_entity_id=original_entity_id,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            source_merge_event_id=source_merge_event_id,
        )
        split_policy = evaluate_split(split_ctx)
        if not split_policy.allowed:
            return {
                "allowed": False,
                "error": split_policy.error,
                "reason_codes": split_policy.reason_codes,
            }

        new_entity_id = str(uuid.uuid4())

        split_event_id = await self._audit.record_split(
            tenant_id=tenant_id,
            original_entity_id=original_entity_id,
            resulting_entity_ids=[original_entity_id, new_entity_id],
            reason=reason,
            actor_type=actor_type,
            actor_id=actor_id,
            source_merge_event_id=source_merge_event_id,
        )

        # Revoke same_as edges
        revoked_edges = await self._graph.revoke_edges_after_split(
            tenant_id, original_entity_id
        )
        self._metrics.record_split(tenant_id=tenant_id)

        return {
            "allowed": True,
            "split_event_id": split_event_id,
            "original_entity_id": original_entity_id,
            "new_entity_id": new_entity_id,
            "revoked_edge_ids": revoked_edges,
            "reason_codes": split_policy.reason_codes,
        }

    async def recompute(
        self,
        tenant_id: str,
        entity_id: Optional[str] = None,
        event_ids: Optional[list[str]] = None,
        reason: str = "recompute",
    ) -> dict:
        """
        Recompute identity resolution for an entity or event set.
        Idempotent — will not create duplicate aliases or edges.
        """
        # In a full implementation this would replay events through the resolver.
        # Here we return a stub response acknowledging the request.
        return {
            "status": "queued",
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "event_ids": event_ids or [],
            "reason": reason,
            "note": "Recompute queued for background processing",
        }

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _write_relationship_edges(
        self,
        raw_signals: list,
        canonical_entity_id: str,
        tenant_id: str,
        confidence: float,
        confidence_tier: ConfidenceTier,
        reason_codes: list[str],
        source_event_ids: list[str],
        consent_snapshot: Optional[dict],
    ) -> None:
        for sig in raw_signals:
            if sig.type == IdentitySignalType.AGENT_ID:
                await self._graph.write_agent_delegation_edge(
                    tenant_id, canonical_entity_id, sig.value,
                    confidence, confidence_tier, reason_codes, source_event_ids,
                )
            elif sig.type == IdentitySignalType.ORG_ID:
                await self._graph.write_org_membership_edge(
                    tenant_id, canonical_entity_id, sig.value,
                    confidence, confidence_tier, reason_codes, source_event_ids,
                )
            elif sig.type == IdentitySignalType.CAMPAIGN_ID:
                await self._graph.write_campaign_edge(
                    tenant_id, canonical_entity_id, sig.value,
                    confidence, confidence_tier, reason_codes, source_event_ids,
                )
            elif sig.type == IdentitySignalType.JOURNEY_ID:
                await self._graph.write_journey_edge(
                    tenant_id, canonical_entity_id, sig.value,
                    confidence, confidence_tier, reason_codes, source_event_ids,
                )
            elif sig.type in (
                IdentitySignalType.WALLET_ADDRESS,
                IdentitySignalType.WALLET_SIGNATURE_VERIFIED,
            ):
                is_verified = sig.type == IdentitySignalType.WALLET_SIGNATURE_VERIFIED
                h, _ = _hash_signal(sig.type, sig.value, tenant_id)
                if h:
                    await self._graph.write_wallet_edge(
                        tenant_id, canonical_entity_id, h,
                        is_verified, confidence, confidence_tier,
                        reason_codes, source_event_ids, consent_snapshot,
                    )


# ── Module-level helpers ──────────────────────────────────────────────────────

def _hash_signal(
    sig_type: IdentitySignalType, value: str, tenant_id: str
) -> tuple[str, str]:
    """
    Hash a signal value and return (hash, display_redacted).
    Non-sensitive types return (value_as_is, value_or_display).
    """
    if not value:
        return "", ""

    if sig_type == IdentitySignalType.EMAIL_HASH:
        from .hashing import hash_email
        h = hash_email(value, tenant_id)
        return h, redact_display(value, "email_hash")

    if sig_type == IdentitySignalType.PHONE_HASH:
        from .hashing import hash_phone
        h = hash_phone(value, tenant_id)
        return h, redact_display(value, "phone_hash")

    if sig_type == IdentitySignalType.DEVICE_FINGERPRINT:
        h = hash_fingerprint(value)
        return h, redact_display(value, "device_fingerprint")

    if sig_type in (
        IdentitySignalType.WALLET_ADDRESS,
        IdentitySignalType.WALLET_SIGNATURE_VERIFIED,
    ):
        h = hash_wallet(value)
        return h, redact_display(value, "wallet_address")

    if sig_type == IdentitySignalType.EXTERNAL_ID:
        h = hash_external_id(value, tenant_id)
        return h, redact_display(value, "external_id")

    # Non-sensitive: return as-is
    return value, value[:16] if len(value) > 16 else value


def _has_strong_signal(types: list[IdentitySignalType]) -> bool:
    strong = {
        IdentitySignalType.USER_ID,
        IdentitySignalType.EXTERNAL_ID,
        IdentitySignalType.EMAIL_HASH,
        IdentitySignalType.PHONE_HASH,
        IdentitySignalType.WALLET_SIGNATURE_VERIFIED,
    }
    return any(t in strong for t in types)


def _infer_entity_type(signals: list) -> EntityType:
    for sig in signals:
        if sig.type == IdentitySignalType.USER_ID:
            return EntityType.HUMAN
        if sig.type == IdentitySignalType.AGENT_ID:
            return EntityType.AGENT
        if sig.type == IdentitySignalType.ORG_ID:
            return EntityType.ORGANIZATION
        if sig.type == IdentitySignalType.WALLET_ADDRESS:
            return EntityType.WALLET
    return EntityType.ANONYMOUS_VISITOR


def _blocked_reason_category(reason_codes: list[str]) -> str:
    from .models import (
        REASON_CROSS_TENANT_BLOCKED,
        REASON_FINGERPRINT_ONLY_BLOCKED,
        REASON_CONSENT_BLOCKS_LINK,
    )
    if REASON_CROSS_TENANT_BLOCKED in reason_codes:
        return "cross_tenant"
    if REASON_FINGERPRINT_ONLY_BLOCKED in reason_codes:
        return "fingerprint_only"
    if REASON_CONSENT_BLOCKS_LINK in reason_codes:
        return "consent"
    return "other"


def _extract_consent(event: dict) -> Optional[dict]:
    ctx = event.get("context") or {}
    return ctx.get("consent") or None
