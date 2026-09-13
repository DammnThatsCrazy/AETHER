"""Cross-network message correlation.

Observations for one message arrive from independent chains in ANY order
(a delivery leg may be seen before its source leg). The correlation engine
finds-or-creates the message row keyed (tenant, provider_kind,
correlation_key), merges endpoint references, applies the lifecycle engine,
appends transition rows, and emits interop_message_correlated exactly once —
when both source and destination references are first present together.
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.interop_repos import InteropMessageEventRepo, InteropMessageRepo
from services.interop.foundation import (
    PUBLIC_TENANT,
    deterministic_id,
    deterministic_idempotency_key,
    make_event,
    utc_now_iso,
)
from services.interop.lifecycle import LifecycleEngine

SCHEMA_VERSION = "1.0.0"

# phase → (lifecycle status, timestamp column, endpoint side)
_PHASE_MAP: dict[str, tuple[str, str, Optional[str]]] = {
    "sent": ("source_confirmed", "source_observed_at", "source"),
    "source_pending": ("source_pending", "source_observed_at", "source"),
    "verified": ("verified", "verified_at", None),
    "delivered": ("delivered", "delivered_at", "destination"),
    "executed": ("executed", "executed_at", "destination"),
    "settled": ("settled", "settled_at", None),
    "failed": ("failed", "terminal_at", None),
}

_PHASE_EVENT: dict[str, str] = {
    "sent": "interop_message_sent_observed",
    "source_pending": "interop_message_discovered",
    "verified": "interop_message_verified",
    "delivered": "interop_message_delivered",
    "executed": "interop_message_executed_observed",
    "settled": "interop_message_settled",
    "failed": "interop_message_failed",
}


class CorrelationEngine:
    def __init__(
        self,
        message_repo: Optional[InteropMessageRepo] = None,
        event_repo: Optional[InteropMessageEventRepo] = None,
    ) -> None:
        self.messages = message_repo or InteropMessageRepo()
        self.transitions = event_repo or InteropMessageEventRepo()

    async def ingest_observation(
        self, tenant_id: str, observation: dict[str, Any],
    ) -> dict[str, Any]:
        phase = observation.get("phase", "")
        if phase == "reorged":
            return await self._handle_reorg(tenant_id, observation)
        if phase not in _PHASE_MAP:
            return {"accepted": False, "reason": f"unknown_phase:{phase}", "emitted_events": []}

        correlation_key = observation["correlation_key"]
        provider_kind = observation.get("provider_kind", "unknown")
        status, timestamp_column, side = _PHASE_MAP[phase]
        observed_at = observation.get("observed_at") or utc_now_iso()
        emitted: list[dict] = []

        existing = await self.messages.find_one({
            "tenant_id": tenant_id,
            "provider_kind": provider_kind,
            "correlation_key": correlation_key,
        })

        endpoint_ref = observation.get("endpoint_ref")
        if existing is None:
            out_of_order = phase not in ("sent", "source_pending")
            basis = f"{tenant_id}|{provider_kind}|{correlation_key}"
            record = {
                "tenant_id": tenant_id,
                "interop_message_id": deterministic_id("iomsg_", basis),
                "tenant_scope": "public" if tenant_id == PUBLIC_TENANT else "tenant",
                "schema_version": SCHEMA_VERSION,
                "provider_id": observation.get("provider_id", provider_kind),
                "provider_kind": provider_kind,
                "protocol_product": observation.get("protocol_product", "messaging"),
                "correlation_key": correlation_key,
                "provider_message_refs": observation.get("provider_message_refs", []),
                "source": endpoint_ref if side == "source" else {},
                "destination": endpoint_ref if side == "destination" else None,
                "path_id": observation.get(
                    "path_id",
                    f"{provider_kind}:{observation.get('source_network_id', 'unknown')}"
                    f"->{observation.get('destination_network_id', 'unknown')}",
                ),
                "sequence": observation.get("sequence"),
                "payload_hash": observation.get("payload_hash"),
                "payload_type": observation.get("payload_type"),
                "status": status,
                "provider_native_status": observation.get("provider_native_stage"),
                "technical_outcome": "unknown",
                timestamp_column: observed_at,
                "confidence": observation.get("confidence", "0.9"),
                "data_freshness": "backfill" if out_of_order else "live",
                "provider_extension": {
                    **(observation.get("provider_extension") or {}),
                    **({"discovered_out_of_order": True} if out_of_order else {}),
                },
                "idempotency_key": deterministic_idempotency_key(basis),
                "evidence": None,
                "execution_by_aether": False,
            }
            await self.messages.insert(record)
            transition = LifecycleEngine.apply(
                tenant_id, record["interop_message_id"], "discovered", status,
                observed_at, observation.get("provider_native_stage"),
            )
            if transition.transition_record:
                await self.transitions.insert(transition.transition_record)
            emitted.append(make_event(_PHASE_EVENT[phase], tenant_id, {
                "interop_message_id": record["interop_message_id"],
                "correlation_key": correlation_key,
                "status": status,
                "path_id": record["path_id"],
            }))
            correlated = bool(record.get("source")) and bool(record.get("destination"))
            if correlated:
                emitted.append(self._correlated_event(tenant_id, record))
            return {
                "accepted": True,
                "interop_message_id": record["interop_message_id"],
                "status": status,
                "out_of_order": out_of_order,
                "emitted_events": emitted,
            }

        # Existing message: merge refs, apply lifecycle, append transition.
        message_id = existing["interop_message_id"]
        was_correlated = bool(existing.get("source")) and bool(existing.get("destination"))
        changes: dict[str, Any] = {}
        if side == "source" and not existing.get("source") and endpoint_ref:
            changes["source"] = endpoint_ref
        if side == "destination" and not existing.get("destination") and endpoint_ref:
            changes["destination"] = endpoint_ref
        if not existing.get(timestamp_column):
            changes[timestamp_column] = observed_at

        result = LifecycleEngine.apply(
            tenant_id, message_id, existing["status"], status,
            observed_at, observation.get("provider_native_stage"),
        )
        if result.applied:
            changes["status"] = result.new_status
            changes["provider_native_status"] = observation.get("provider_native_stage")
            if result.new_status == "settled":
                changes["technical_outcome"] = "success"
                changes["terminal_at"] = observed_at
            if result.transition_record:
                await self.transitions.insert(result.transition_record)
            emitted.append(make_event(_PHASE_EVENT[phase], tenant_id, {
                "interop_message_id": message_id,
                "correlation_key": correlation_key,
                "status": result.new_status,
            }))
        if changes:
            await self.messages.update_by_key(
                {"tenant_id": tenant_id, "interop_message_id": message_id}, changes,
            )
        now_source = changes.get("source") or existing.get("source")
        now_destination = changes.get("destination") or existing.get("destination")
        if not was_correlated and now_source and now_destination:
            merged = {**existing, **changes}
            emitted.append(self._correlated_event(tenant_id, merged))

        return {
            "accepted": True,
            "interop_message_id": message_id,
            "status": result.new_status if result.applied else existing["status"],
            "lifecycle_reason": result.reason,
            "emitted_events": emitted,
        }

    async def _handle_reorg(
        self, tenant_id: str, observation: dict[str, Any],
    ) -> dict[str, Any]:
        """Chain reorg on a network: move affected non-terminal messages to
        'reorged' and append transitions. Terminal messages are untouched."""
        from services.interop.lifecycle import TERMINAL_STATES

        network_id = observation.get("network_id", "")
        from_block = int(observation.get("from_block", 0))
        emitted: list[dict] = []
        affected = 0
        candidates = await self.messages.find_many({"tenant_id": tenant_id}, limit=10_000)
        for message in candidates:
            if message["status"] in TERMINAL_STATES:
                continue
            source = message.get("source") or {}
            if source.get("network_id") != network_id:
                continue
            block_number = int(source.get("block_number") or 0)
            if block_number < from_block:
                continue
            result = LifecycleEngine.apply(
                tenant_id, message["interop_message_id"], message["status"],
                "reorged", observation.get("observed_at", ""), "chain_reorg",
            )
            if not result.applied:
                continue
            await self.messages.update_by_key(
                {"tenant_id": tenant_id, "interop_message_id": message["interop_message_id"]},
                {"status": "reorged", "data_freshness": "stale"},
            )
            if result.transition_record:
                await self.transitions.insert(result.transition_record)
            affected += 1
            emitted.append(make_event("interop_message_reorged", tenant_id, {
                "interop_message_id": message["interop_message_id"],
                "network_id": network_id,
                "from_block": from_block,
            }))
        return {"accepted": True, "reorg_affected": affected, "emitted_events": emitted}

    def _correlated_event(self, tenant_id: str, message: dict[str, Any]) -> dict[str, Any]:
        return make_event("interop_message_correlated", tenant_id, {
            "interop_message_id": message["interop_message_id"],
            "correlation_key": message["correlation_key"],
            "path_id": message.get("path_id"),
        })
