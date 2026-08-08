#!/usr/bin/env bash
# =============================================================================
# Aether Platform — Kafka Topic Provisioning
#
# Creates all 131 topics with explicit partition counts and retention settings.
# Safe to re-run: uses --if-not-exists on creation.
#
# Usage (against local Docker Compose):
#   ./kafka_topics.sh
#
# Usage (against remote broker):
#   KAFKA_BOOTSTRAP=kafka.prod.example.com:9092 ./kafka_topics.sh
#
# Partition strategy:
#   high-throughput  (SDK ingest, identity, analytics): 12 partitions
#   standard         (ML, agent, campaign, commerce):    6 partitions
#   low-volume       (consent, governance, extraction):  3 partitions
#
# Retention:
#   raw ingest   : 7 days  (replayed on schema evolution)
#   operational  : 14 days (investigation, governance, x402)
#   audit / legal: 90 days (extraction defense, consent)
# =============================================================================

set -euo pipefail

KAFKA_BOOTSTRAP="${KAFKA_BOOTSTRAP:-localhost:9092}"
KAFKA_CMD="kafka-topics --bootstrap-server ${KAFKA_BOOTSTRAP}"

_create() {
    local topic="$1" partitions="$2" retention_ms="$3"
    ${KAFKA_CMD} --create \
        --topic "${topic}" \
        --partitions "${partitions}" \
        --replication-factor 1 \
        --config "retention.ms=${retention_ms}" \
        --if-not-exists 2>/dev/null || true
}

DAY_MS=86400000
WEEK_MS=$((7 * DAY_MS))
TWO_WEEKS_MS=$((14 * DAY_MS))
NINETY_DAY_MS=$((90 * DAY_MS))

echo "Provisioning Aether Kafka topics on ${KAFKA_BOOTSTRAP}..."

# ── SDK Ingest (high-throughput, 7-day retention) ─────────────────
_create aether.sdk.events.raw       12 ${WEEK_MS}
_create aether.sdk.events.validated 12 ${WEEK_MS}
_create aether.api.feed.raw         12 ${WEEK_MS}

# ── Identity (high-throughput, 14-day retention) ──────────────────
_create aether.identity.resolved       12 ${TWO_WEEKS_MS}
_create aether.identity.merged         12 ${TWO_WEEKS_MS}
_create aether.profile.updated          6 ${TWO_WEEKS_MS}
_create aether.identity.fingerprint.observed 6 ${TWO_WEEKS_MS}
_create aether.identity.ip.observed    6 ${TWO_WEEKS_MS}
_create aether.resolution.evaluated    6 ${TWO_WEEKS_MS}
_create aether.resolution.auto_merged  6 ${TWO_WEEKS_MS}
_create aether.resolution.flagged      6 ${TWO_WEEKS_MS}
_create aether.resolution.approved     6 ${TWO_WEEKS_MS}
_create aether.resolution.rejected     6 ${TWO_WEEKS_MS}

# ── Analytics & ML (standard, 14-day) ────────────────────────────
_create aether.analytics.session.scored 6 ${TWO_WEEKS_MS}
_create aether.analytics.anomaly        6 ${TWO_WEEKS_MS}
_create aether.ml.prediction            6 ${TWO_WEEKS_MS}
_create aether.ml.model.updated         3 ${TWO_WEEKS_MS}
_create aether.campaign.attribution              6 ${TWO_WEEKS_MS}
_create aether.campaign.created                  6 ${TWO_WEEKS_MS}
_create aether.campaign.updated                  6 ${TWO_WEEKS_MS}
_create aether.campaign.deleted                  6 ${TWO_WEEKS_MS}
_create aether.campaign.touchpoint.recorded      6 ${TWO_WEEKS_MS}

# ── Agent (standard, 14-day) ─────────────────────────────────────
_create aether.agent.discovery              6 ${TWO_WEEKS_MS}
_create aether.agent.enrichment             6 ${TWO_WEEKS_MS}
_create aether.agent.task.started           6 ${TWO_WEEKS_MS}
_create aether.agent.task.completed         6 ${TWO_WEEKS_MS}
_create aether.agent.decision.made          6 ${TWO_WEEKS_MS}
_create aether.agent.state.snapshot         6 ${TWO_WEEKS_MS}
_create aether.agent.ground_truth           6 ${TWO_WEEKS_MS}
_create aether.agent.notification.sent      6 ${TWO_WEEKS_MS}
_create aether.agent.recommendation.made    6 ${TWO_WEEKS_MS}
_create aether.agent.result.delivered       6 ${TWO_WEEKS_MS}
_create aether.agent.escalation.raised      6 ${TWO_WEEKS_MS}

# ── Commerce & x402 (standard, 14-day) ───────────────────────────
_create aether.commerce.payment.sent             6 ${TWO_WEEKS_MS}
_create aether.commerce.agent.hired              6 ${TWO_WEEKS_MS}
_create aether.commerce.service.purchased        6 ${TWO_WEEKS_MS}
_create aether.commerce.fee.eliminated           6 ${TWO_WEEKS_MS}
_create aether.commerce.challenge.issued         6 ${TWO_WEEKS_MS}
_create aether.commerce.requirement.generated    6 ${TWO_WEEKS_MS}
_create aether.commerce.approval.requested       6 ${TWO_WEEKS_MS}
_create aether.commerce.approval.assigned        6 ${TWO_WEEKS_MS}
_create aether.commerce.approval.approved        6 ${TWO_WEEKS_MS}
_create aether.commerce.approval.rejected        6 ${TWO_WEEKS_MS}
_create aether.commerce.approval.escalated       6 ${TWO_WEEKS_MS}
_create aether.commerce.approval.expired         6 ${TWO_WEEKS_MS}
_create aether.commerce.approval.revoked         6 ${TWO_WEEKS_MS}
_create aether.commerce.payment.submitted        6 ${TWO_WEEKS_MS}
_create aether.commerce.verification.started     6 ${TWO_WEEKS_MS}
_create aether.commerce.verification.succeeded   6 ${TWO_WEEKS_MS}
_create aether.commerce.verification.failed      6 ${TWO_WEEKS_MS}
_create aether.commerce.settlement.started       6 ${TWO_WEEKS_MS}
_create aether.commerce.settlement.pending       6 ${TWO_WEEKS_MS}
_create aether.commerce.settlement.completed     6 ${TWO_WEEKS_MS}
_create aether.commerce.settlement.failed        6 ${TWO_WEEKS_MS}
_create aether.commerce.entitlement.granted      6 ${TWO_WEEKS_MS}
_create aether.commerce.entitlement.reused       6 ${TWO_WEEKS_MS}
_create aether.commerce.entitlement.revoked      6 ${TWO_WEEKS_MS}
_create aether.commerce.entitlement.expired      6 ${TWO_WEEKS_MS}
_create aether.commerce.access.granted           6 ${TWO_WEEKS_MS}
_create aether.commerce.access.denied            6 ${TWO_WEEKS_MS}
_create aether.commerce.policy.denied            6 ${TWO_WEEKS_MS}
_create aether.commerce.facilitator.route_selected 6 ${TWO_WEEKS_MS}
_create aether.commerce.kyber.action_logged      6 ${TWO_WEEKS_MS}
_create aether.commerce.operator.action_logged   6 ${TWO_WEEKS_MS}
_create aether.commerce.replay.executed          6 ${TWO_WEEKS_MS}
_create aether.commerce.reconciliation.task_created   6 ${TWO_WEEKS_MS}
_create aether.commerce.reconciliation.task_resolved  6 ${TWO_WEEKS_MS}
_create aether.x402.payment.captured             6 ${TWO_WEEKS_MS}

# ── On-Chain (standard, 14-day) ───────────────────────────────────
_create aether.onchain.action.recorded    6 ${TWO_WEEKS_MS}
_create aether.onchain.contract.deployed  6 ${TWO_WEEKS_MS}
_create aether.onchain.contract.called    6 ${TWO_WEEKS_MS}

# ── Profile 360 — Entity/Delegation/Flow/Behavior (standard, 14-day)
_create aether.entity.created               6 ${TWO_WEEKS_MS}
_create aether.entity.updated               6 ${TWO_WEEKS_MS}
_create aether.entity.identifier.linked     6 ${TWO_WEEKS_MS}
_create aether.entity.identifier.unlinked   6 ${TWO_WEEKS_MS}
_create aether.entity.membership.added      6 ${TWO_WEEKS_MS}
_create aether.delegation.created           6 ${TWO_WEEKS_MS}
_create aether.delegation.revoked           6 ${TWO_WEEKS_MS}
_create aether.delegation.validated         6 ${TWO_WEEKS_MS}
_create aether.delegation.rejected          6 ${TWO_WEEKS_MS}
_create aether.flow.transfer                6 ${TWO_WEEKS_MS}
_create aether.flow.wallet.linked           6 ${TWO_WEEKS_MS}
_create aether.behavior.session.started     6 ${TWO_WEEKS_MS}
_create aether.behavior.session.ended       6 ${TWO_WEEKS_MS}
_create aether.behavior.event.recorded      6 ${TWO_WEEKS_MS}
_create aether.behavior.pattern.detected    6 ${TWO_WEEKS_MS}
_create aether.behavior.profile.updated     6 ${TWO_WEEKS_MS}
_create aether.journey.started              6 ${TWO_WEEKS_MS}
_create aether.journey.actor.joined         6 ${TWO_WEEKS_MS}
_create aether.journey.actor.left           6 ${TWO_WEEKS_MS}
_create aether.journey.converted            6 ${TWO_WEEKS_MS}
_create aether.journey.abandoned            6 ${TWO_WEEKS_MS}

# ── Agent Execution (standard, 14-day) ───────────────────────────
_create aether.agent.execution.started    6 ${TWO_WEEKS_MS}
_create aether.agent.execution.completed  6 ${TWO_WEEKS_MS}
_create aether.agent.execution.failed     6 ${TWO_WEEKS_MS}
_create aether.agent.execution.recovered  6 ${TWO_WEEKS_MS}

# ── Investigation & Governance (standard, 14-day) ─────────────────
_create aether.investigation.case.created    6 ${TWO_WEEKS_MS}
_create aether.investigation.case.updated    6 ${TWO_WEEKS_MS}
_create aether.investigation.status.changed  6 ${TWO_WEEKS_MS}
_create aether.governance.decision.evaluated 6 ${TWO_WEEKS_MS}

# ── Event Replay (standard, 14-day) ──────────────────────────────
_create aether.event.replay.submitted  6 ${TWO_WEEKS_MS}
_create aether.event.replay.completed  6 ${TWO_WEEKS_MS}
_create aether.event.replay.cancelled  6 ${TWO_WEEKS_MS}

# ── Consent & DSR (audit, 90-day) ────────────────────────────────
_create aether.consent.updated      3 ${NINETY_DAY_MS}
_create aether.consent.dsr          3 ${NINETY_DAY_MS}

# ── Extraction Defense Mesh (audit, 90-day) ───────────────────────
_create aether.extraction.request.seen          3 ${NINETY_DAY_MS}
_create aether.extraction.identity.resolved     3 ${NINETY_DAY_MS}
_create aether.extraction.signal.computed       3 ${NINETY_DAY_MS}
_create aether.extraction.score.updated         3 ${NINETY_DAY_MS}
_create aether.extraction.policy.applied        3 ${NINETY_DAY_MS}
_create aether.extraction.canary.hit            3 ${NINETY_DAY_MS}
_create aether.extraction.alert.opened          3 ${NINETY_DAY_MS}
_create aether.extraction.cluster.escalated     3 ${NINETY_DAY_MS}

# ── Cognitive Integrity System (epistemic middleware, 14/90-day) ─
# Mutation lifecycle — high-volume operational, 14-day
_create aether.cis.graph.mutation.created              6 ${TWO_WEEKS_MS}
_create aether.cis.graph.mutation.accepted             6 ${TWO_WEEKS_MS}
_create aether.cis.graph.mutation.rejected             6 ${TWO_WEEKS_MS}
# Mutation quarantine — governance/audit, 90-day
_create aether.cis.graph.mutation.quarantined          3 ${NINETY_DAY_MS}
# Retrieval observability — high-volume operational, 14-day
_create aether.cis.retrieval.executed                  6 ${TWO_WEEKS_MS}
_create aether.cis.retrieval.context.selected          6 ${TWO_WEEKS_MS}
# Retrieval anomalies — governance/audit, 90-day
_create aether.cis.retrieval.instability.detected      3 ${NINETY_DAY_MS}
_create aether.cis.retrieval.contamination.detected    3 ${NINETY_DAY_MS}
# Generation telemetry — high-volume operational, 14-day
_create aether.cis.generation.started                  6 ${TWO_WEEKS_MS}
_create aether.cis.generation.completed                6 ${TWO_WEEKS_MS}
_create aether.cis.generation.claim.extracted          6 ${TWO_WEEKS_MS}
# Generation anomalies — governance/audit, 90-day
_create aether.cis.generation.ungrounded.detected      3 ${NINETY_DAY_MS}
# Semantic drift — low-volume anomaly detection, 90-day
_create aether.cis.semantic.drift.detected                        3 ${NINETY_DAY_MS}
_create aether.cis.semantic.cluster.instability.detected          3 ${NINETY_DAY_MS}
_create aether.cis.semantic.embedding.deformation.detected        3 ${NINETY_DAY_MS}
# Reasoning chains — operational, 14-day; anomalies 90-day
_create aether.cis.reasoning.chain.created             6 ${TWO_WEEKS_MS}
_create aether.cis.reasoning.contradiction.detected    3 ${NINETY_DAY_MS}
_create aether.cis.reasoning.recursion.detected        3 ${NINETY_DAY_MS}
# Quarantine workflow — governance/audit, 90-day
_create aether.cis.quarantine.initiated                3 ${NINETY_DAY_MS}
_create aether.cis.quarantine.released                 3 ${NINETY_DAY_MS}
_create aether.cis.quarantine.escalated                3 ${NINETY_DAY_MS}

# ── Dead Letter Queue (operational, 14-day) ───────────────────────
_create aether.dlq                              3 ${TWO_WEEKS_MS}

echo ""
echo "Topic provisioning complete. Listing topics:"
${KAFKA_CMD} --list | grep "^aether\." | sort
