"""
Aether Backend — Interoperability Intelligence Repositories

Typed repositories for the Alembic-owned interop tables (migration
20260708_interop_intelligence). Protocol-neutral, observation-only domain:
every tenant-scoped row carries execution_by_aether=False (fail-closed CHECK
in the DDL). Public-scope rows use the sentinel tenant 'public'.

The message table is the one mutable current-state projection (status,
timestamps, destination merge); the append-only interop_message_events
table carries the immutable transition trail.
"""

from __future__ import annotations

from repositories.typed_repo import TypedTableRepository

_TENANT_COMMON = ("idempotency_key", "evidence", "execution_by_aether")


class InteropProviderRepo(TypedTableRepository):
    table_name = "interop_providers"
    columns = (
        "provider_id", "provider_kind", "display_name", "protocol_products",
        "supported_versions", "implementation_status", "capabilities", "data",
    )
    jsonb_columns = frozenset({"protocol_products", "supported_versions", "capabilities", "data"})
    conflict_key = ("provider_id",)


class InteropGatewayRepo(TypedTableRepository):
    table_name = "interop_gateways"
    columns = (
        "gateway_id", "provider_id", "network_id", "native_chain_id",
        "provider_network_id", "gateway_address", "gateway_role", "active",
    )
    conflict_key = ("gateway_id",)


class InteropPathRepo(TypedTableRepository):
    table_name = "interop_paths"
    columns = (
        "path_id", "provider_id", "source_network_id", "destination_network_id",
        "source_gateway_id", "destination_gateway_id", "first_seen_at", "last_seen_at",
    )
    conflict_key = ("path_id",)


class InteropApplicationRepo(TypedTableRepository):
    table_name = "interop_applications"
    columns = (
        "application_id", "network_id", "contract_address", "display_name",
        "owner_entity_ref", "provider_ids", "first_seen_at",
    )
    jsonb_columns = frozenset({"owner_entity_ref", "provider_ids"})
    conflict_key = ("application_id",)


class VerificationActorRepo(TypedTableRepository):
    table_name = "interop_verification_actors"
    columns = (
        "verification_actor_id", "provider_id", "display_name", "actor_address",
        "networks", "actor_role",
    )
    jsonb_columns = frozenset({"networks"})
    conflict_key = ("verification_actor_id",)


class DeliveryActorRepo(TypedTableRepository):
    table_name = "interop_delivery_actors"
    columns = (
        "delivery_actor_id", "provider_id", "display_name", "actor_address", "networks",
    )
    jsonb_columns = frozenset({"networks"})
    conflict_key = ("delivery_actor_id",)


class InteropMessageRepo(TypedTableRepository):
    """Current-state message projection (mutable via update_by_key); the
    immutable trail lives in InteropMessageEventRepo."""

    table_name = "interop_messages"
    columns = (
        "tenant_id", "interop_message_id", "tenant_scope", "schema_version",
        "provider_id", "provider_kind", "protocol_product", "correlation_key",
        "provider_message_refs", "source", "destination", "path_id", "sequence",
        "payload_hash", "payload_type", "status", "provider_native_status",
        "technical_outcome", "source_observed_at", "source_confirmed_at",
        "verified_at", "delivered_at", "executed_at", "settled_at", "terminal_at",
        "security_snapshot_id", "intent_id", "fee_total", "fee_asset_id",
        "confidence", "data_freshness", "provider_extension", *_TENANT_COMMON,
    )
    jsonb_columns = frozenset({
        "provider_message_refs", "source", "destination", "provider_extension", "evidence",
    })
    conflict_key = ("tenant_id", "provider_kind", "correlation_key")


class InteropMessageEventRepo(TypedTableRepository):
    """Append-only lifecycle transition log."""

    table_name = "interop_message_events"
    columns = (
        "tenant_id", "transition_id", "interop_message_id", "from_status",
        "to_status", "provider_native_stage", "observed_at", "evidence_ref",
        *_TENANT_COMMON,
    )
    jsonb_columns = frozenset({"evidence"})


class InteropIntentRepo(TypedTableRepository):
    table_name = "interop_intents"
    columns = (
        "tenant_id", "intent_id", "provider_id", "initiator_entity_ref",
        "initiator_address", "source_network_id", "destination_network_id",
        "requested_asset_id", "requested_amount", "status",
        "created_at_provider", "resolved_at", *_TENANT_COMMON,
    )
    jsonb_columns = frozenset({"initiator_entity_ref", "evidence"})


class InteropAssetLegRepo(TypedTableRepository):
    table_name = "interop_asset_legs"
    columns = (
        "tenant_id", "asset_leg_id", "interop_message_id", "intent_id", "leg_type",
        "network_id", "asset_id", "token_address", "amount_atomic", "amount_decimal",
        "from_address", "to_address", "transaction_hash", "observed_at", *_TENANT_COMMON,
    )
    jsonb_columns = frozenset({"evidence"})


class SecurityPolicySnapshotRepo(TypedTableRepository):
    table_name = "interop_security_policy_snapshots"
    columns = (
        "tenant_id", "security_snapshot_id", "provider_id", "path_id",
        "effective_block_number", "verification_model", "required_verifier_ids",
        "optional_verifier_ids", "optional_threshold", "confirmations_required",
        "delivery_actor_ids", "module_addresses", "content_hash", "captured_at",
        *_TENANT_COMMON,
    )
    jsonb_columns = frozenset({
        "required_verifier_ids", "optional_verifier_ids", "delivery_actor_ids",
        "module_addresses", "evidence",
    })
    conflict_key = ("tenant_id", "path_id", "content_hash")


class DeliveryAttemptRepo(TypedTableRepository):
    table_name = "interop_delivery_attempts"
    columns = (
        "tenant_id", "delivery_attempt_id", "interop_message_id", "attempt_number",
        "status", "delivery_actor_id", "transaction_hash", "error_class",
        "observed_at", *_TENANT_COMMON,
    )
    jsonb_columns = frozenset({"evidence"})


class InteropProviderCheckpointRepo(TypedTableRepository):
    table_name = "interop_provider_checkpoints"
    columns = (
        "tenant_id", "checkpoint_id", "provider_id", "network_id",
        "last_scanned_block", "confirmed_block", "advanced_at", *_TENANT_COMMON,
    )
    jsonb_columns = frozenset({"evidence"})
    conflict_key = ("tenant_id", "provider_id", "network_id")


class InteropReconciliationRepo(TypedTableRepository):
    table_name = "interop_reconciliation_records"
    columns = (
        "tenant_id", "reconciliation_id", "interop_message_id", "correlation_key",
        "status", "sources_compared", "difference_note", "resolved_at", *_TENANT_COMMON,
    )
    jsonb_columns = frozenset({"sources_compared", "evidence"})


class SilverInteropFactRepo(TypedTableRepository):
    table_name = "silver_interop_facts"
    columns = (
        "tenant_id", "idempotency_key", "source_event_id", "entity_id", "event_type",
        "occurred_at", "payload", "provider_id", "path_id", "interop_message_id",
        "status", "amount_decimal",
    )
    jsonb_columns = frozenset({"payload"})
