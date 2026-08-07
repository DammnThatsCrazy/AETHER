#!/usr/bin/env python3
"""Validate that metrics.increment() calls in ingestion/connector/webhook paths
use only the canonical meter event names defined here.

Exits 0 if all names are canonical, 1 if non-canonical names are found.
Non-canonical names in test files are ignored.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "Backend Architecture" / "aether-backend"

# Canonical meter names for the ingestion spine.
# Names not in this set are flagged as non-canonical in the checked paths.
CANONICAL_NAMES: frozenset[str] = frozenset({
    # Ingestion
    "sdk_event_ingested",
    "event_ingested",
    "event_rejected",
    "event_duplicate",
    "event_replayed",
    "dlq_event_created",
    "webhook_ingested",
    "connector_sync",
    # Ingestion batch (internal counters in batch.py — more granular, allowed)
    "ingestion_batch_received_total",
    "ingestion_event_accepted_total",
    "ingestion_event_duplicate_total",
    "ingestion_event_rejected_total",
    "ingestion_validation_failed_total",
    "ingestion_consent_blocked_total",
    "ingestion_consent_authority_blocked_total",
    "ingestion_sensitive_scrub_total",
    "ingestion_request_privacy_blocked_total",
    "ingestion_data_policy_blocked_total",
    # Temporal enforcement (temporal_enforcement.py hook in batch.py; mode ladder
    # off/shadow/warn/enforce — meters identical in every active mode)
    "ingestion_temporal_state_total",
    "ingestion_temporal_reason_total",
    "ingestion_temporal_blocked_total",
    # Sequence integrity (sequence_integrity.py hook in batch.py; stateless
    # in-batch gap/duplicate detection over context.sequence.event — metrics only)
    "ingestion_sequence_gap_total",
    "ingestion_sequence_duplicate_total",
    # Server-derived context enrichment (context_enricher.py hook in batch.py)
    "ingestion_context_enrichment_total",
    # Ingestion V2 — typed Bronze + transactional outbox (PR 5, bronze_bulk.py)
    "ingestion_v2_batch_received_total",
    "ingestion_v2_bronze_accepted_total",
    "ingestion_v2_bronze_duplicate_total",
    "ingestion_v2_transaction_rollback_total",
    # Ingestion V2 — event-outbox relay worker (PR 6, outbox_relay.py/workers.py)
    "ingestion_outbox_relay_claimed_total",
    "ingestion_outbox_relay_published_total",
    "ingestion_outbox_relay_retried_total",
    "ingestion_outbox_relay_dead_lettered_total",
    "ingestion_bronze_relay_skip_total",
    # Payment Rail Observability (services/integrations/providers/payment_rails)
    "payment_rail_event_duplicate_total",
    "payment_rail_event_rejected_total",
    "payment_rail_sessions_upserted_total",
    "payment_rail_status_downgrade_blocked_total",
    "payment_rail_webhook_handled_total",
    "payment_rail_webhook_rejected_total",
    "payment_rail_webhook_rate_limited_total",
    "payment_rail_tenant_action_rate_limited_total",
    # Payment Rail sync/staleness worker (services/.../payment_rails/sync_worker.py)
    "payment_rail_sync_cycle_total",
    "payment_rail_sync_session_scanned_total",
    "payment_rail_sync_provider_pulled_total",
    "payment_rail_sync_transitioned_total",
    "payment_rail_sync_error_total",
    # Payment Rail canonical-repair worker (services/.../payment_rails/repair_worker.py)
    "payment_rail_repair_cycle_total",
    "payment_rail_repair_error_total",
    "payment_rail_repair_dead_lettered_total",
    # Payment Rail durable webhook endpoint routing (services/.../payment_rails/routes.py)
    "payment_rail_webhook_unknown_endpoint_total",
    # Payment Rail provider polling health (services/.../payment_rails/service.py)
    "payment_rail_provider_poll_degraded_total",
    # Card-linked payment rails (services/card_linked_payments)
    "card_linked_flows_upserted_total",
    "card_linked_audit_total",
    "card_linked_gold_materialized_total",
    "identity_resolve_error_total",
    "ingestion_bronze_write_failed_total",
    "ingestion_publish_failed_total",
    # Semantic Intelligence classify pipeline (services/semantic_intelligence/
    # service.py) — contracted 1:1 with the aether_semantic_health alert group,
    # the semantic-pipeline dashboard, and
    # tests/unit/test_semantic_observability_assets.py. Counters use
    # metrics.increment(); the latency histogram and the two gauges below are
    # emitted via metrics.timing()/metrics.gauge() on the same collector and
    # are registered here so the full contract lives in one place.
    "aether_semantic_observations_classified_total",
    "aether_semantic_observations_abstained_total",
    "aether_semantic_observations_quarantined_total",
    "aether_semantic_classify_latency_ms",
    "aether_semantic_review_queue_open",
    "aether_semantic_replay_jobs_active",
    # Comparison Intelligence (services/intelligence/comparison — WP3.5)
    "comparison_runs_total",
    "comparison_findings_total",
    "comparison_findings_suppressed_total",
    "comparison_finding_dispositions_total",
    "comparison_finding_investigations_total",
    "comparison_finding_recommendations_total",
    "comparison_refusals_total",
    "comparison_scenarios_total",
    # Exploration Fabric (services/exploration — WP3.4)
    "exploration_queries_total",
    "exploration_validate_total",
    "exploration_facets_total",
    "exploration_facet_suppressed_total",
    "exploration_filter_dispositions_total",
    "exploration_saved_views_total",
    # Stablecoin / Derivatives / Interoperability intelligence
    "stablecoin_observation_ingested",
    "stablecoin_flow_materialized",
    "derivatives_event_ingested",
    "derivatives_reconciliation_run",
    "derivatives_stream_gap_detected",
    "interop_observation_ingested",
    "interop_message_correlated",
    "interop_reconciliation_run",
    # Feeds / Dune
    "api_feeds_ingested",
    "api_feeds_duplicate",
    "dune_poll_tenant_cycle",
    "dune_poll_tenant_error",
    "dune_poll_cycle_complete",
    "dune_poll_loop_error",
    # Retention
    "retention_sweep_swept",
    "retention_sweep_errors",
    "retention_sweep_loop_error",
    # Connectors + webhooks
    "connector_pull_success",
    "connector_pull_error",
    "connector_health_checked",
    "connector_webhook_received_total",
    "connector_webhook_rejected_total",
    # Ingestion workers (granular internal counters)
    "ingestion_bronze_write_latency_ms",
    "sdk_bronze_written_total",
    "ingestion_silver_written_total",
    # Silver fact projection (multi-projector dispatch — ADR-C3)
    "silver_facts_written_total",
    "silver_projection_dead_letters_total",
    # AI Outcome Efficiency / AI Economics (ai_invocation_observed → ai_execution_facts)
    "ai_execution_fact_written_total",
    "ai_execution_fact_duplicate_total",
    "ai_execution_fact_conflict_total",
    "ai_execution_fact_rejected_total",
    "ai_price_card_created_total",
    # Storage plane — Elastic Data Plane descriptor/object layer (FT-7,
    # shared/storage/manager.py + shared/storage/reconciler.py)
    "storage_object_externalized_total",
    "storage_object_hydrated_total",
    "storage_hydrate_checksum_mismatch_total",
    "storage_reconcile_run_total",
    "storage_reconcile_missing_object_total",
    "storage_reconcile_orphan_object_total",
    "storage_reconcile_checksum_drift_total",
    # Object-backed Bronze + cross-store lifecycle (FT-8,
    # shared/storage/compaction.py + shared/storage/lifecycle.py +
    # services/storage_lifecycle/worker.py)
    "storage_bronze_compaction_run_total",
    "storage_bronze_compaction_stale_rebuild_total",
    "storage_bronze_rows_externalized_total",
    "storage_bronze_payload_route_hot_total",
    "storage_bronze_payload_route_hydrated_total",
    "storage_lifecycle_retention_object_deleted_total",
    "storage_lifecycle_retention_object_tombstoned_total",
    "storage_lifecycle_retention_row_deleted_total",
    "storage_lifecycle_retention_row_tombstoned_total",
    "storage_lifecycle_legal_hold_blocked_total",
    "storage_lifecycle_dsr_records_erased_total",
    "storage_lifecycle_dsr_objects_repacked_total",
    "storage_lifecycle_sweep_error_total",
    # Dune feeder
    "dune_feeder_promoted",
    "dune_feeder_rejected",
    # Population snapshots (existing)
    "population_snapshot_taken",
    "population_snapshot_failed",
    # Generic counters used widely — not flagged
    "events_ingested",
})

# Only check these directories for ingestion/connector meter names
CHECKED_DIRS = [
    BACKEND / "services" / "ingestion",
    BACKEND / "services" / "integrations",
]


def main() -> int:
    issues: list[str] = []
    increment_re = re.compile(r'metrics\.increment\(\s*["\']([^"\']+)["\']')

    for search_dir in CHECKED_DIRS:
        if not search_dir.exists():
            continue
        for py_file in search_dir.rglob("*.py"):
            if "test" in py_file.name:
                continue
            text = py_file.read_text()
            for match in increment_re.finditer(text):
                name = match.group(1)
                if name not in CANONICAL_NAMES:
                    line_no = text[: match.start()].count("\n") + 1
                    issues.append(f"  {py_file.relative_to(ROOT)}:{line_no}  {name!r}")

    if not issues:
        print("OK: all metrics.increment() names are canonical")
        return 0

    print("NON-CANONICAL meter names found (add to CANONICAL_NAMES or rename):", file=sys.stderr)
    for issue in issues:
        print(issue, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
