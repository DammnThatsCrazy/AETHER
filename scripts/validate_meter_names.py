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
    # Ingestion V2 — typed Bronze + transactional outbox (PR 5, bronze_bulk.py)
    "ingestion_v2_batch_received_total",
    "ingestion_v2_bronze_accepted_total",
    "ingestion_v2_bronze_duplicate_total",
    "ingestion_v2_transaction_rollback_total",
    # Payment Rail Observability (services/integrations/providers/payment_rails)
    "payment_rail_event_duplicate_total",
    "payment_rail_event_rejected_total",
    "payment_rail_sessions_upserted_total",
    "payment_rail_status_downgrade_blocked_total",
    "payment_rail_webhook_handled_total",
    "payment_rail_webhook_rejected_total",
    # Payment Rail sync/staleness worker (services/.../payment_rails/sync_worker.py)
    "payment_rail_sync_cycle_total",
    "payment_rail_sync_session_scanned_total",
    "payment_rail_sync_provider_pulled_total",
    "payment_rail_sync_transitioned_total",
    "payment_rail_sync_error_total",
    # Card-linked payment rails (services/card_linked_payments)
    "card_linked_flows_upserted_total",
    "card_linked_audit_total",
    "card_linked_gold_materialized_total",
    "identity_resolve_error_total",
    "ingestion_bronze_write_failed_total",
    "ingestion_publish_failed_total",
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
