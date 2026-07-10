"""Targeting intent lifecycle + eligibility snapshot computation."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from shared.common.common import BadRequestError
from shared.logger.logger import get_logger, metrics

from services.targeting_intelligence.models import (
    ClusterTargetingRule,
    EvidenceRef,
    TargetingEligibilitySnapshot,
    TargetingIntent,
    utc_now_iso,
)
from services.targeting_intelligence.policy import (
    ClusterSignals,
    is_eligible,
    is_holdout,
    resolve_cluster,
)
from services.targeting_intelligence.repository import (
    TargetingRepositories,
    get_targeting_repositories,
)

logger = get_logger("aether.targeting.service")

# Caller-injectable async reader: cluster_id -> member count (or None when the
# cluster subsystem has no data). Kept injectable for tests and to avoid a
# hard dependency on graph availability.
ClusterMemberReader = Callable[[str, str], Awaitable[Optional[int]]]


async def _default_member_reader(tenant_id: str, cluster_id: str) -> Optional[int]:
    try:
        from shared.graph.graph import GraphClient
        graph = GraphClient()
        neighbors = await graph.get_neighbors(cluster_id)
        return len(neighbors) if neighbors is not None else None
    except Exception:  # pragma: no cover — graph optional in local/test
        return None


class TargetingIntentService:
    def __init__(
        self,
        repositories: Optional[TargetingRepositories] = None,
        member_reader: ClusterMemberReader = _default_member_reader,
    ) -> None:
        self.repos = repositories or get_targeting_repositories()
        self._member_reader = member_reader

    # ── Intents ───────────────────────────────────────────────────────────

    async def create_intent(self, tenant_id: str, payload: dict, actor: str) -> dict:
        # Non-execution invariants: reject payloads claiming Aether executes.
        if payload.get("executionByAether") not in (None, False):
            raise BadRequestError("executionByAether must be false — Aether never executes")
        if payload.get("externalExecutionRequired") not in (None, True):
            raise BadRequestError("externalExecutionRequired must be true")
        payload = {**payload, "tenantId": tenant_id}
        intent = TargetingIntent.model_validate(payload)
        if not (intent.includeClusters or intent.referenceClusters or intent.rules):
            raise BadRequestError("An intent needs include/reference clusters or rules")
        record = await self.repos.intents.save(tenant_id, intent.model_dump(mode="json"))
        await self.repos.audit.record(tenant_id, "intent_created",
                                      {"intentId": intent.id}, actor)
        metrics.increment("targeting_intents_created_total")
        return record

    async def update_intent(self, tenant_id: str, intent_id: str,
                            changes: dict, actor: str) -> dict:
        record = await self.repos.intents.get(tenant_id, intent_id)
        for frozen in ("executionByAether", "externalExecutionRequired", "id", "tenantId"):
            changes.pop(frozen, None)
        record.update(changes)
        record["updatedAt"] = utc_now_iso()
        intent = TargetingIntent.model_validate(record)  # re-validate invariants
        saved = await self.repos.intents.save(tenant_id, intent.model_dump(mode="json"))
        await self.repos.audit.record(tenant_id, "intent_updated",
                                      {"intentId": intent_id}, actor)
        return saved

    # ── Eligibility snapshots ─────────────────────────────────────────────

    def _effective_rules(self, intent: TargetingIntent) -> list[ClusterTargetingRule]:
        """Union of explicit rules and the list-shorthand fields."""
        rules = list(intent.rules)
        listed = {(r.clusterId, r.ruleType) for r in rules}

        def _add(cluster_ids: Optional[list[str]], rule_type: str) -> None:
            for cluster_id in cluster_ids or []:
                if (cluster_id, rule_type) not in listed:
                    rules.append(ClusterTargetingRule(
                        clusterId=cluster_id, ruleType=rule_type,  # type: ignore[arg-type]
                    ))

        _add(intent.includeClusters, "include")
        _add(intent.excludeClusters, "exclude")
        _add(intent.referenceClusters, "reference")
        _add(intent.holdoutClusters, "holdout")
        return rules

    async def compute_eligibility_snapshot(
        self,
        tenant_id: str,
        intent_id: str,
        as_of: str,
        actor: str = "system",
        cluster_signals: Optional[dict[str, ClusterSignals]] = None,
    ) -> dict:
        """Compute (or deterministically recompute) the snapshot for an asOf."""
        intent = TargetingIntent.model_validate(
            await self.repos.intents.get(tenant_id, intent_id)
        )
        rules = self._effective_rules(intent)
        cluster_ids = sorted({r.clusterId for r in rules})
        signals = cluster_signals or {}

        eligible: list[str] = []
        excluded: list[str] = []
        holdouts: list[str] = []
        decisions = []
        member_counts: dict[str, int] = {}
        evidence: list[EvidenceRef] = list(intent.evidenceRefs)

        for cluster_id in cluster_ids:
            decision = resolve_cluster(tenant_id, cluster_id, rules,
                                       signals.get(cluster_id))
            decisions.append(decision)
            await self.repos.policy_decisions.save(
                tenant_id, decision.model_dump(mode="json")
            )
            if is_eligible(decision):
                eligible.append(cluster_id)
            elif is_holdout(decision):
                holdouts.append(cluster_id)
            else:
                excluded.append(cluster_id)

            count = await self._member_reader(tenant_id, cluster_id)
            if count is None:
                evidence.append(EvidenceRef(
                    id=f"gap:{cluster_id}", type="annotation",
                    source="targeting_intelligence",
                    uri=None, observedAt=utc_now_iso(),
                ))
                member_counts[cluster_id] = 0
            else:
                member_counts[cluster_id] = count

        snapshot = TargetingEligibilitySnapshot(
            tenantId=tenant_id,
            campaignId=intent.campaignId,
            targetingIntentId=intent_id,
            asOf=as_of,
            eligibleClusters=eligible,
            excludedClusters=excluded,
            holdoutClusters=holdouts,
            identityConfidenceThreshold=intent.minIdentityConfidence,
            clusterMembershipThreshold=intent.minClusterMembershipScore,
            pathConfidenceThreshold=intent.minPathConfidence,
            evidenceCoverageThreshold=intent.minEvidenceCoverage,
            clusterMemberCounts=member_counts,
            evidenceRefs=evidence,
            policyDecisionIds=[d.id for d in decisions],
        )
        record = await self.repos.snapshots.save_snapshot(
            tenant_id, snapshot.model_dump(mode="json")
        )
        await self.repos.audit.record(
            tenant_id, "eligibility_snapshot_computed",
            {"intentId": intent_id, "asOf": as_of, "snapshotId": record["snapshotId"]},
            actor,
        )
        metrics.increment("targeting_snapshots_computed_total")
        return record


_service: Optional[TargetingIntentService] = None


def get_targeting_service() -> TargetingIntentService:
    global _service
    if _service is None:
        _service = TargetingIntentService()
    return _service
