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
from dataclasses import dataclass, field
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
from .merge_policy import (
    MergePolicyContext,
    NON_MERGE_ELIGIBLE_SIGNAL_NAMES,
    evaluate,
    evaluate_operator_merge,
)
from .metrics import IdentityMetrics
from .models import (
    ConfidenceTier,
    EdgeType,
    EntityType,
    IdentityResolutionDecision,
    IdentitySignalType,
    MergeDecision,
    SubjectStatus,
    REASON_CAMPAIGN_ONLY_SAMENESS_BLOCKED,
    REASON_CROSS_TENANT_FRAGMENT_BLOCKED,
    REASON_FRAGMENT_SPLIT,
    REASON_IDENTITY_CYCLE_BLOCKED,
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

# Signal *values* that never constitute identity sameness. A fragment made up
# solely of these carries no real identity evidence, so splitting it onto its
# own / another entity would assert sameness on campaign/attribution grounds
# alone — which is exactly what must be blocked. Combines the resolver's
# attribution-only set with merge_policy's non-merge-eligible telemetry denylist.
_NON_IDENTITY_SIGNAL_VALUES: frozenset[str] = frozenset(
    {t.value for t in _ATTRIBUTION_ONLY} | set(NON_MERGE_ELIGIBLE_SIGNAL_NAMES)
)


def _is_merge_eligible_signal(signal_value: str) -> bool:
    """True if a signal value can carry identity evidence (not campaign-only)."""
    return bool(signal_value) and signal_value not in _NON_IDENTITY_SIGNAL_VALUES


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


@dataclass
class _FragmentSplitPlan:
    """Result of analysing a fragment split (shared by preview + execute).

    A plan is either a rejection (``allowed=False`` + ``rejection_reason``) or
    an approved, fully-resolved plan describing exactly what execution will
    move/revoke. Analysis is strictly read-only, so the same plan powers the
    non-mutating preview and the mutating execute path.
    """
    allowed: bool
    entity_id: str
    mode: str
    reason: str
    actor_type: str
    actor_id: str
    source_merge_event_id: Optional[str]
    target_entity_id: Optional[str]        # resolved dest (None → mint new at execute)
    alias_rows: list[dict] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    edges_to_revoke: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    source_entity_type: Optional[str] = None
    rejection_reason: Optional[str] = None
    error: Optional[str] = None


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

        # Recompute path: caller provides pre-hashed signals to bypass
        # extract/normalize/hash/persist steps (observations already in DB).
        _pre_hashed = event.get("_pre_hashed_signals")
        if _pre_hashed is not None:
            raw_signals: list = []
            hashed_signals: list[tuple[IdentitySignalType, str, str]] = []
            for item in _pre_hashed:
                try:
                    sig_type = IdentitySignalType(item["type"])
                    hashed_signals.append((sig_type, item["hash"], item.get("display", "")))
                except (ValueError, KeyError):
                    continue
            if not hashed_signals:
                return IdentityResolutionDecision(
                    tenant_id=tenant_id,
                    canonical_entity_id="",
                    decision=MergeDecision.NOOP,
                    confidence=0.0,
                    confidence_tier=ConfidenceTier.WEAK,
                    reason_codes=["no_signals"],
                )
        else:
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
            hashed_signals = []
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

        # ── 4b. Check suppression rules ───────────────────────────────────
        suppressed_types: list[IdentitySignalType] = []
        filtered_signals: list[tuple[IdentitySignalType, str, str]] = []
        for (sig_type, sig_hash, display) in hashed_signals:
            is_suppressed = await self._repo.check_suppression(
                tenant_id, sig_type.value, sig_hash
            )
            if is_suppressed:
                suppressed_types.append(sig_type)
                self._metrics.record_blocked("suppression")
            else:
                filtered_signals.append((sig_type, sig_hash, display))
        if suppressed_types:
            logger.info(
                "Suppressed signals for tenant=%s: %s",
                tenant_id, [t.value for t in suppressed_types],
            )
        # Build exact (type, hash) pairs that were suppressed, then filter raw_signals
        # using those pairs only — not the entire type — so unsuppressed signals of the
        # same type (e.g., a second wallet address) are not incorrectly removed.
        filtered_hash_set = {(t, h) for (t, h, _) in filtered_signals}
        suppressed_pairs: set[tuple[IdentitySignalType, str]] = {
            (t, h) for (t, h, _) in hashed_signals if (t, h) not in filtered_hash_set
        }
        hashed_signals = filtered_signals
        if suppressed_pairs:
            raw_signals = [
                sig for sig in raw_signals
                if (sig.type, _hash_signal(sig.type, sig.value, tenant_id)[0])
                not in suppressed_pairs
            ]

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

        _signal_types_for_type_infer = (
            [sig.type for sig in raw_signals]
            if raw_signals
            else [t for (t, _, _) in hashed_signals]
        )
        if policy_result.decision == MergeDecision.CREATE or not existing_entity_ids:
            canonical_entity_id = str(uuid.uuid4())
            entity_type = _infer_entity_type_from_types(_signal_types_for_type_infer)
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
                entity_type = _infer_entity_type_from_types(_signal_types_for_type_infer)
                await self._repo.create_subject(
                    tenant_id=tenant_id,
                    canonical_entity_id=canonical_entity_id,
                    entity_type=entity_type,
                )

        # ── 8b. Link this event's observations to the resolved entity ─────
        # Observations are persisted at step 4 before the canonical entity is
        # known; link them now so get_observations_for_entity (and entity-scoped
        # recompute) can actually find them.
        if canonical_entity_id and event_id:
            await self._repo.set_observations_canonical_entity(
                tenant_id, event_id, canonical_entity_id
            )

        # ── 9. Link aliases ───────────────────────────────────────────────
        linked_aliases: list[str] = []
        if policy_result.decision not in (MergeDecision.BLOCKED, MergeDecision.REJECT):
            if raw_signals:
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
            else:
                # Pre-hashed path: use hashed_signals directly (observations already persisted)
                for (sig_type, sig_hash, display) in hashed_signals:
                    if sig_type in _ATTRIBUTION_ONLY:
                        continue
                    alias = await self._repo.upsert_alias(
                        tenant_id=tenant_id,
                        canonical_entity_id=canonical_entity_id,
                        alias_type=sig_type,
                        alias_value_hash=sig_hash,
                        alias_display_value_redacted=display,
                        source="recompute",
                        source_event_id=event_id,
                        source_platform=None,
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
                await self._repo.mark_subject_merged_by_canonical_id(
                    tenant_id, from_id, canonical_entity_id
                )
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
        await self._repo.mark_subject_merged_by_canonical_id(
            tenant_id, secondary_entity_id, primary_entity_id
        )
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

    # ── Fragment-aware identity repair (PR5 slice) ────────────────────────

    async def _same_as_edges_between(
        self, tenant_id: str, entity_a: str, entity_b: str
    ) -> list[str]:
        """Active SAME_AS edge ids incident to entity_a whose other end is entity_b."""
        edges = await self._repo.get_entity_graph(tenant_id, entity_a)
        result: list[str] = []
        for e in edges:
            if e.get("edge_type") != EdgeType.SAME_AS.value or e.get("revoked_at"):
                continue
            endpoints = {e.get("source_entity_id"), e.get("target_entity_id")}
            if entity_b in endpoints:
                result.append(e["id"])
        return result

    async def _analyze_fragment_split(
        self,
        tenant_id: str,
        entity_id: str,
        alias_ids: list[str],
        observation_ids: list[str],
        mode: str,
        actor_id: str,
        actor_type: str,
        reason: str,
        target_entity_id: Optional[str],
        source_merge_event_id: Optional[str],
    ) -> _FragmentSplitPlan:
        """Read-only validation + impact analysis for a fragment split.

        Enforces: operator/admin split policy, per-fragment tenant match (no
        cross-tenant), fragment ownership by the source entity, campaign-only
        sameness blocking, and identity-cycle prevention. Performs NO writes —
        it is safe to call from the non-mutating preview endpoint.
        """
        risk_notes: list[str] = []
        base_codes: list[str] = []

        def reject(
            rejection_reason: str, error: str, codes: Optional[list[str]] = None
        ) -> _FragmentSplitPlan:
            return _FragmentSplitPlan(
                allowed=False,
                entity_id=entity_id,
                mode=mode,
                reason=reason,
                actor_type=actor_type,
                actor_id=actor_id,
                source_merge_event_id=source_merge_event_id,
                target_entity_id=None,
                risk_notes=risk_notes,
                reason_codes=_dedupe_preserve(base_codes + (codes or [])),
                rejection_reason=rejection_reason,
                error=error,
            )

        # 1. Operator/admin split policy gate (actor, entity, reason).
        policy = evaluate_split(SplitPolicyContext(
            tenant_id=tenant_id,
            original_entity_id=entity_id,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            source_merge_event_id=source_merge_event_id,
            proposed_entity_ids=[target_entity_id] if target_entity_id else [],
        ))
        if not policy.allowed:
            return reject("split_policy_denied", policy.error or "split not permitted", policy.reason_codes)
        base_codes = list(policy.reason_codes)  # includes REASON_MANUAL_OPERATOR_SPLIT

        # 2. A fragment must name at least one member.
        if not alias_ids and not observation_ids:
            return reject(
                "empty_fragment",
                "fragment must include at least one alias_id or observation_id",
            )

        # 3. Source entity (subject may be absent if it only owns aliases).
        source_subject = await self._repo.get_subject_by_canonical_entity_id(
            tenant_id, entity_id
        )
        source_entity_type = (
            source_subject.get("entity_type") if source_subject else None
        )

        # 4. Validate alias fragments: tenant + ownership; collect signal values.
        alias_rows: list[dict] = []
        fragment_signal_values: list[str] = []
        for alias_id in alias_ids:
            row = await self._repo.get_alias_by_id(alias_id)
            if row is None:
                return reject("fragment_alias_not_found", f"alias {alias_id!r} not found")
            if row.get("tenant_id") != tenant_id:
                return reject(
                    REASON_CROSS_TENANT_FRAGMENT_BLOCKED,
                    f"alias {alias_id!r} belongs to another tenant",
                    [REASON_CROSS_TENANT_FRAGMENT_BLOCKED],
                )
            if row.get("canonical_entity_id") != entity_id:
                return reject(
                    "fragment_not_owned_by_entity",
                    f"alias {alias_id!r} is not owned by entity {entity_id!r}",
                )
            fragment_signal_values.append(str(row.get("alias_type", "")))
            if row.get("revoked_at"):
                risk_notes.append(
                    f"alias {alias_id} already revoked — skipped (idempotent)"
                )
                continue
            alias_rows.append(row)

        # 5. Validate observation fragments: tenant + ownership.
        valid_observation_ids: list[str] = []
        for obs_id in observation_ids:
            row = await self._repo.get_observation_by_id(obs_id)
            if row is None:
                return reject(
                    "fragment_observation_not_found", f"observation {obs_id!r} not found"
                )
            if row.get("tenant_id") != tenant_id:
                return reject(
                    REASON_CROSS_TENANT_FRAGMENT_BLOCKED,
                    f"observation {obs_id!r} belongs to another tenant",
                    [REASON_CROSS_TENANT_FRAGMENT_BLOCKED],
                )
            obs_entity = row.get("canonical_entity_id")
            if obs_entity not in (None, "", entity_id):
                return reject(
                    "fragment_not_owned_by_entity",
                    f"observation {obs_id!r} is not owned by entity {entity_id!r}",
                )
            fragment_signal_values.append(str(row.get("signal_type", "")))
            valid_observation_ids.append(obs_id)

        # 6. Campaign-only sameness guard (merge_policy signal classes).
        if fragment_signal_values and not any(
            _is_merge_eligible_signal(v) for v in fragment_signal_values
        ):
            return reject(
                REASON_CAMPAIGN_ONLY_SAMENESS_BLOCKED,
                "fragment carries only campaign/attribution signals — campaign "
                "attribution never establishes identity sameness",
                [REASON_CAMPAIGN_ONLY_SAMENESS_BLOCKED],
            )

        # 7. Resolve the destination entity per mode + identity-cycle guards.
        resolved_target: Optional[str] = None
        if mode == "create_new_entity":
            resolved_target = None  # brand-new id minted at execution time
            risk_notes.append(
                "create_new_entity: a brand-new canonical entity will be minted"
            )
        elif mode == "restore_pre_merge_entity":
            if not source_merge_event_id:
                return reject(
                    "source_merge_event_required",
                    "restore_pre_merge_entity requires source_merge_event_id",
                )
            merge_event = await self._repo.get_merge_event_by_id(
                tenant_id, source_merge_event_id
            )
            if merge_event is None:
                return reject(
                    "merge_event_not_found",
                    f"merge event {source_merge_event_id!r} not found for tenant",
                )
            pre_merge_id = merge_event.get("from_entity_id") or ""
            if not pre_merge_id:
                return reject(
                    "merge_event_missing_from_entity",
                    "merge event has no from_entity_id to restore",
                )
            survivors = {
                merge_event.get("into_entity_id"),
                merge_event.get("resulting_entity_id"),
            }
            if entity_id not in survivors:
                risk_notes.append(
                    f"entity {entity_id} is not the recorded survivor of merge "
                    f"{source_merge_event_id}"
                )
            if pre_merge_id == entity_id:
                return reject(
                    REASON_IDENTITY_CYCLE_BLOCKED,
                    "pre-merge entity equals the entity being split",
                    [REASON_IDENTITY_CYCLE_BLOCKED],
                )
            resolved_target = pre_merge_id
        elif mode == "move_to_existing_entity":
            if not target_entity_id:
                return reject(
                    "target_entity_required",
                    "move_to_existing_entity requires target_entity_id",
                )
            if target_entity_id == entity_id:
                return reject(
                    REASON_IDENTITY_CYCLE_BLOCKED,
                    "cannot move a fragment onto the same entity",
                    [REASON_IDENTITY_CYCLE_BLOCKED],
                )
            target_subject = await self._repo.get_subject_by_canonical_entity_id(
                tenant_id, target_entity_id
            )
            if target_subject is None:
                return reject(
                    "target_entity_not_found",
                    f"target entity {target_entity_id!r} not found for tenant",
                )
            if target_subject.get("status") != SubjectStatus.ACTIVE.value:
                return reject(
                    "target_entity_not_active",
                    f"target entity {target_entity_id!r} is not active",
                )
            # Cycle guard: target must not redirect back to the source entity.
            target_survivor = await self._repo.resolve_surviving_canonical_entity_id(
                tenant_id, target_entity_id
            )
            if target_survivor == entity_id:
                return reject(
                    REASON_IDENTITY_CYCLE_BLOCKED,
                    "target entity's survivor chain resolves back to the source entity",
                    [REASON_IDENTITY_CYCLE_BLOCKED],
                )
            resolved_target = target_entity_id
        else:
            return reject("unknown_split_mode", f"unknown split mode {mode!r}")

        # 8. SAME_AS edges to revoke between source and the resolved target.
        edges_to_revoke: list[str] = []
        if resolved_target:
            edges_to_revoke = await self._same_as_edges_between(
                tenant_id, entity_id, resolved_target
            )
            if not edges_to_revoke:
                risk_notes.append(
                    "no active SAME_AS edges between source and target to revoke"
                )
        else:
            risk_notes.append("create_new_entity: no pre-existing SAME_AS edges to revoke")

        if not alias_rows and not valid_observation_ids:
            risk_notes.append(
                "all fragment members already moved/revoked — split will be a no-op"
            )

        return _FragmentSplitPlan(
            allowed=True,
            entity_id=entity_id,
            mode=mode,
            reason=reason,
            actor_type=actor_type,
            actor_id=actor_id,
            source_merge_event_id=source_merge_event_id,
            target_entity_id=resolved_target,
            alias_rows=alias_rows,
            observation_ids=valid_observation_ids,
            edges_to_revoke=edges_to_revoke,
            risk_notes=risk_notes,
            reason_codes=_dedupe_preserve(base_codes + [REASON_FRAGMENT_SPLIT]),
            source_entity_type=source_entity_type,
        )

    async def preview_fragment_split(
        self,
        tenant_id: str,
        entity_id: str,
        fragments: dict,
        mode: str,
        actor_id: str,
        actor_type: str = "operator",
        reason: str = "fragment_repair",
        target_entity_id: Optional[str] = None,
        source_merge_event_id: Optional[str] = None,
    ) -> dict:
        """NON-MUTATING impact analysis for splitting a fragment off an entity.

        Reports what execution WOULD move/revoke plus risk notes. When the
        split is not permitted, returns ``allowed=False`` with a typed
        ``rejection_reason`` (e.g. ``campaign_only_sameness_blocked``) rather
        than raising — the operator still gets the full analysis.
        """
        plan = await self._analyze_fragment_split(
            tenant_id=tenant_id,
            entity_id=entity_id,
            alias_ids=list((fragments or {}).get("alias_ids") or []),
            observation_ids=list((fragments or {}).get("observation_ids") or []),
            mode=mode,
            actor_id=actor_id,
            actor_type=actor_type,
            reason=reason,
            target_entity_id=target_entity_id,
            source_merge_event_id=source_merge_event_id,
        )
        return {
            "allowed": plan.allowed,
            "entity_id": entity_id,
            "mode": mode,
            "target_entity_id": plan.target_entity_id,
            "aliases_to_reassign": [r["id"] for r in plan.alias_rows],
            "observations_to_relink": list(plan.observation_ids),
            "edges_to_revoke": list(plan.edges_to_revoke),
            "risk_notes": plan.risk_notes,
            "reason_codes": plan.reason_codes,
            "rejection_reason": plan.rejection_reason,
            "error": plan.error,
        }

    async def fragment_split(
        self,
        tenant_id: str,
        entity_id: str,
        fragments: dict,
        mode: str,
        actor_id: str,
        actor_type: str = "operator",
        reason: str = "fragment_repair",
        target_entity_id: Optional[str] = None,
        source_merge_event_id: Optional[str] = None,
    ) -> dict:
        """Execute a fragment-aware identity split.

        Modes:
          * ``create_new_entity`` — mint a new canonical entity for the fragment.
          * ``restore_pre_merge_entity`` — restore the pre-merge id recovered
            from ``source_merge_event_id`` (a merge event's ``from_entity_id``).
          * ``move_to_existing_entity`` — move the fragment onto an existing,
            active, same-tenant entity.

        Reassigns the named aliases (lineage-preserving: recreate on target,
        revoke on source — never leaving duplicate active aliases), relinks the
        named observations, appends an immutable split event carrying the exact
        fragment payload, and selectively revokes SAME_AS edges between the
        fragment and the original. Returns a structured result; failures surface
        as ``allowed=False`` with a typed ``rejection_reason``.
        """
        alias_ids = list((fragments or {}).get("alias_ids") or [])
        observation_ids = list((fragments or {}).get("observation_ids") or [])

        plan = await self._analyze_fragment_split(
            tenant_id=tenant_id,
            entity_id=entity_id,
            alias_ids=alias_ids,
            observation_ids=observation_ids,
            mode=mode,
            actor_id=actor_id,
            actor_type=actor_type,
            reason=reason,
            target_entity_id=target_entity_id,
            source_merge_event_id=source_merge_event_id,
        )
        if not plan.allowed:
            return {
                "allowed": False,
                "entity_id": entity_id,
                "mode": mode,
                "split_event_id": None,
                "resulting_entity_id": None,
                "moved_alias_ids": [],
                "moved_observation_ids": [],
                "revoked_edge_ids": [],
                "reason_codes": plan.reason_codes,
                "rejection_reason": plan.rejection_reason,
                "error": plan.error,
            }

        entity_type = plan.source_entity_type or EntityType.HUMAN.value

        # ── Resolve / create the destination entity ───────────────────────
        if mode == "create_new_entity":
            resulting_entity_id = str(uuid.uuid4())
            await self._repo.create_subject(tenant_id, resulting_entity_id, entity_type)
        elif mode == "restore_pre_merge_entity":
            resulting_entity_id = plan.target_entity_id or str(uuid.uuid4())
            # Reactivate (or recreate) the pre-merge subject as a live identity.
            await self._repo.restore_subject(tenant_id, resulting_entity_id, entity_type)
        else:  # move_to_existing_entity — target already validated active
            resulting_entity_id = plan.target_entity_id  # type: ignore[assignment]

        # ── Reassign aliases (lineage-preserving) ─────────────────────────
        moved_alias_ids: list[str] = []
        for alias in plan.alias_rows:
            new_alias = await self._repo.upsert_alias(
                tenant_id=tenant_id,
                canonical_entity_id=resulting_entity_id,
                alias_type=alias.get("alias_type"),
                alias_value_hash=alias.get("alias_value_hash", ""),
                alias_display_value_redacted=alias.get("alias_display_value_redacted", ""),
                source="fragment_split",
                source_event_id=alias.get("source_event_id", ""),
                source_platform=alias.get("source_platform", ""),
                confidence=alias.get("confidence", 1.0),
                confidence_tier=alias.get("confidence_tier", ConfidenceTier.DETERMINISTIC),
                consent_snapshot=alias.get("consent_snapshot"),
            )
            # Revoke the original on the source so no duplicate active alias exists.
            await self._repo.revoke_alias(alias["id"])
            moved_alias_ids.append(new_alias["id"])

        # ── Relink the named observations ─────────────────────────────────
        moved_observation_ids = await self._repo.relink_observations_to_entity(
            tenant_id, plan.observation_ids, resulting_entity_id
        )

        # ── Selectively revoke SAME_AS edges between fragment and original ─
        # These are the repo-backed (source-of-truth) identity edges. The
        # Neptune-side SAME_AS revoke is wired separately in shared/graph
        # (GraphClient.revoke_edge is intentionally out of scope for this slice).
        revoked_edge_ids: list[str] = []
        for edge_id in plan.edges_to_revoke:
            revoked = await self._repo.revoke_identity_edge(edge_id)
            if revoked and revoked.get("revoked_at"):
                revoked_edge_ids.append(edge_id)

        # ── Append the immutable split event with the fragment payload ────
        split_event = await self._repo.create_split_event(
            tenant_id=tenant_id,
            original_entity_id=entity_id,
            resulting_entity_ids=[entity_id, resulting_entity_id],
            reason=reason,
            actor_type=actor_type,
            actor_id=actor_id,
            source_merge_event_id=source_merge_event_id,
            fragment={
                "alias_ids": alias_ids,
                "observation_ids": observation_ids,
                "moved_alias_ids": moved_alias_ids,
                "moved_observation_ids": moved_observation_ids,
            },
            mode=mode,
        )
        self._metrics.record_split(tenant_id=tenant_id)

        return {
            "allowed": True,
            "entity_id": entity_id,
            "mode": mode,
            "split_event_id": split_event["id"],
            "resulting_entity_id": resulting_entity_id,
            "moved_alias_ids": moved_alias_ids,
            "moved_observation_ids": moved_observation_ids,
            "revoked_edge_ids": revoked_edge_ids,
            "reason_codes": plan.reason_codes,
            "rejection_reason": None,
            "error": None,
        }

    async def suppress_identifier(
        self,
        tenant_id: str,
        identifier_type: str,
        identifier_hash: str,
        reason: str,
        actor_id: str,
        subject_id: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> dict:
        """Suppress a specific identifier hash — it can no longer link identities."""
        rule = await self._repo.create_suppression_rule(
            tenant_id=tenant_id,
            identifier_hash=identifier_hash,
            identifier_type=identifier_type,
            reason=reason,
            created_by=actor_id,
            subject_id=subject_id,
            expires_at=expires_at,
        )
        # Revoke any active aliases using this identifier
        aliases = await self._repo.find_aliases_by_signal(
            tenant_id, identifier_type, identifier_hash
        )
        revoked_alias_ids: list[str] = []
        for alias in aliases:
            if not alias.get("revoked_at"):
                await self._repo.revoke_alias(alias["id"])
                revoked_alias_ids.append(alias["id"])

        await self._audit.record_resolution(
            tenant_id=tenant_id,
            decision=MergeDecision.BLOCKED,
            canonical_entity_id=subject_id or "",
            candidate_entity_ids=[],
            confidence=1.0,
            confidence_tier=ConfidenceTier.DETERMINISTIC,
            reason_codes=["suppression_applied", reason],
            source_event_ids=[],
            policy_result="suppressed",
            consent_snapshot=None,
        )
        self._metrics.record_blocked("suppression")
        return {
            "suppression_id": rule["id"],
            "tenant_id": tenant_id,
            "identifier_type": identifier_type,
            "reason": reason,
            "revoked_alias_ids": revoked_alias_ids,
            "created_at": rule.get("created_at", ""),
            "expires_at": expires_at,
        }

    async def unsuppress_identifier(
        self,
        tenant_id: str,
        suppression_id: str,
        actor_id: str,
    ) -> dict:
        """Revoke a suppression rule."""
        result = await self._repo.revoke_suppression_rule(tenant_id, suppression_id)
        if result is None:
            return {"error": "not_found", "suppression_id": suppression_id}
        return {"revoked": True, "suppression_id": suppression_id, "revoked_by": actor_id}

    async def recompute(
        self,
        tenant_id: str,
        entity_id: Optional[str] = None,
        event_ids: Optional[list[str]] = None,
        reason: str = "recompute",
    ) -> dict:
        """
        Recompute identity resolution by replaying signal observations.
        Idempotent — will not create duplicate aliases or edges.
        """
        if entity_id:
            observations = await self._repo.get_observations_for_entity(
                tenant_id, entity_id, limit=500
            )
        elif event_ids:
            observations = await self._repo.get_observations_for_events(
                tenant_id, event_ids, limit=500
            )
        else:
            return {
                "status": "error",
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "event_ids": event_ids or [],
                "reason": reason,
                "note": "Either entity_id or event_ids is required",
                "events_replayed": 0,
                "decisions": [],
                "errors": 0,
            }

        if not observations:
            return {
                "status": "complete",
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "event_ids": event_ids or [],
                "reason": reason,
                "events_replayed": 0,
                "decisions": [],
                "errors": 0,
            }

        # Group all observations by source_event_id so all signals from one event
        # are replayed together. Using _pre_hashed_signals bypasses re-hashing of
        # already-stored hashes.
        events_map: dict[str, list] = {}
        for obs in observations:
            src_evt_id = obs.get("source_event_id", "")
            if src_evt_id:
                events_map.setdefault(src_evt_id, []).append(obs)

        decisions: list[dict] = []
        errors = 0

        for src_evt_id, event_obs in events_map.items():
            pre_hashed: list[dict] = []
            consent_snapshot_val = event_obs[0].get("consent_snapshot") if event_obs else None
            for obs in event_obs:
                sig_type_str = obs.get("signal_type", "")
                sig_hash = obs.get("signal_value_hash", "")
                if sig_type_str and sig_hash:
                    pre_hashed.append({
                        "type": sig_type_str,
                        "hash": sig_hash,
                        "display": obs.get("raw_value_redacted", ""),
                    })
            if not pre_hashed:
                continue

            synthetic_event: dict = {
                "event_id": src_evt_id,
                "tenant_id": tenant_id,
                "context": {"consent": consent_snapshot_val},
                "_pre_hashed_signals": pre_hashed,
                "source": "recompute",
            }

            try:
                decision = await self._resolve_event_inner(synthetic_event, tenant_id)
                decisions.append({
                    "event_id": src_evt_id,
                    "decision": decision.decision.value,
                    "canonical_entity_id": decision.canonical_entity_id,
                })
            except Exception as exc:
                logger.warning("Recompute replay failed for event %s: %s", src_evt_id, exc)
                errors += 1

        return {
            "status": "complete",
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "event_ids": event_ids or [],
            "reason": reason,
            "events_replayed": len(events_map),
            "decisions": decisions,
            "errors": errors,
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
    return _infer_entity_type_from_types([sig.type for sig in signals])


def _infer_entity_type_from_types(signal_types: list[IdentitySignalType]) -> EntityType:
    for st in signal_types:
        if st == IdentitySignalType.USER_ID:
            return EntityType.HUMAN
        if st == IdentitySignalType.AGENT_ID:
            return EntityType.AGENT
        if st == IdentitySignalType.ORG_ID:
            return EntityType.ORGANIZATION
        if st == IdentitySignalType.WALLET_ADDRESS:
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
