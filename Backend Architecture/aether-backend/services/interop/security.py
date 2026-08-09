"""Security policy snapshots — content-hashed captures of the verification
configuration governing a path. Historical snapshots are immutable; drift is
detected by hash change and emitted as interop_security_policy_changed."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from repositories.interop_repos import SecurityPolicySnapshotRepo
from services.interop.foundation import (
    deterministic_id,
    deterministic_idempotency_key,
    make_event,
    utc_now_iso,
)


def policy_content_hash(policy: dict[str, Any]) -> str:
    """Deterministic hash over the security-relevant fields (sorted)."""
    canonical = {
        "verification_model": policy.get("verification_model", "unknown"),
        "required_verifier_ids": sorted(policy.get("required_verifier_ids", [])),
        "optional_verifier_ids": sorted(policy.get("optional_verifier_ids", [])),
        "optional_threshold": policy.get("optional_threshold"),
        "confirmations_required": policy.get("confirmations_required"),
        "delivery_actor_ids": sorted(policy.get("delivery_actor_ids", [])),
        "module_addresses": dict(sorted((policy.get("module_addresses") or {}).items())),
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(canonical, sort_keys=True).encode()
    ).hexdigest()


class SecurityPolicyService:
    def __init__(self, snapshot_repo: Optional[SecurityPolicySnapshotRepo] = None) -> None:
        self.snapshots = snapshot_repo or SecurityPolicySnapshotRepo()

    async def snapshot_policy(
        self, tenant_id: str, provider_id: str, path_id: str, policy: dict[str, Any],
    ) -> dict[str, Any]:
        content_hash = policy_content_hash(policy)

        previous = await self.snapshots.find_many(
            {"tenant_id": tenant_id, "path_id": path_id},
            limit=1, order_by="captured_at", descending=True,
        )
        previous_hash = previous[0]["content_hash"] if previous else None

        basis = f"{tenant_id}|{path_id}|{content_hash}"
        record = {
            "tenant_id": tenant_id,
            "security_snapshot_id": deterministic_id("iosec_", basis),
            "provider_id": provider_id,
            "path_id": path_id,
            "effective_block_number": policy.get("effective_block_number"),
            "verification_model": policy.get("verification_model", "unknown"),
            "required_verifier_ids": sorted(policy.get("required_verifier_ids", [])),
            "optional_verifier_ids": sorted(policy.get("optional_verifier_ids", [])),
            "optional_threshold": policy.get("optional_threshold"),
            "confirmations_required": policy.get("confirmations_required"),
            "delivery_actor_ids": sorted(policy.get("delivery_actor_ids", [])),
            "module_addresses": policy.get("module_addresses") or {},
            "content_hash": content_hash,
            "captured_at": policy.get("captured_at") or utc_now_iso(),
            "idempotency_key": deterministic_idempotency_key(basis),
            "evidence": None,
            "execution_by_aether": False,
        }
        inserted = await self.snapshots.insert(record)

        emitted: list[dict] = []
        if inserted:
            emitted.append(make_event(
                "interop_security_policy_snapshot_recorded", tenant_id, {
                    "security_snapshot_id": record["security_snapshot_id"],
                    "path_id": path_id,
                    "content_hash": content_hash,
                },
            ))
            if previous_hash and previous_hash != content_hash:
                emitted.append(make_event("interop_security_policy_changed", tenant_id, {
                    "path_id": path_id,
                    "previous_hash": previous_hash,
                    "new_hash": content_hash,
                }))
        return {
            "inserted": inserted,
            "security_snapshot_id": record["security_snapshot_id"],
            "content_hash": content_hash,
            "changed_from_previous": bool(previous_hash and previous_hash != content_hash),
            "emitted_events": emitted,
        }

    async def path_drift(self, tenant_id: str, path_id: str) -> dict[str, Any]:
        rows = await self.snapshots.find_many(
            {"tenant_id": tenant_id, "path_id": path_id},
            limit=100, order_by="captured_at", descending=True,
        )
        hashes = [row["content_hash"] for row in rows]
        return {
            "path_id": path_id,
            "snapshot_count": len(rows),
            "distinct_policies": len(set(hashes)),
            "latest_hash": hashes[0] if hashes else None,
        }


def _policy_from_observation(provider: Any, observation: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Derive a deterministic, offline security policy for one observation.

    Uses the adapter's structural ``security_model()`` (available without
    credentials) plus the observation's network confirmations. The content
    hash changes when the provider's structural verification model changes —
    the drift surface the SecurityPolicyService exists to detect.
    """
    model = getattr(provider, "security_model", None)
    if not callable(model):
        return None
    try:
        sm = model() or {}
    except Exception:  # noqa: BLE001 — structural model unavailable
        return None
    if not sm:
        return None
    endpoint = observation.get("endpoint_ref") or {}
    confirmations = endpoint.get("confirmations_required")
    return {
        "verification_model": sm.get("verification_model", "unknown"),
        "required_verifier_ids": sm.get("required_verifier_ids", []),
        "optional_verifier_ids": sm.get("optional_verifier_ids", []),
        "optional_threshold": sm.get("optional_threshold"),
        "confirmations_required": confirmations if confirmations is not None
        else sm.get("confirmations_required"),
        "delivery_actor_ids": sm.get("delivery_actor_ids", []),
        "module_addresses": sm.get("module_addresses", {}),
        "effective_block_number": endpoint.get("block_number"),
    }


async def scan_security_policy_snapshots(
    tenant_id: str,
    observations: list[dict[str, Any]],
    service: Optional[SecurityPolicyService] = None,
) -> list[dict[str, Any]]:
    """Snapshot-time caller for :meth:`SecurityPolicyService.snapshot_policy`.

    Wired into the scan worker (gated on the caller's own flag). For every
    observation that references a path and a provider whose structural
    security model is available offline, snapshots the derived policy and
    collects the emitted events (snapshot recorded / policy changed). Paths
    whose provider exposes no structural model are skipped — a snapshot is
    never fabricated.
    """
    service = service or SecurityPolicyService()
    emitted: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for observation in observations:
        provider_id = observation.get("provider_id") or observation.get("provider_kind")
        path_id = observation.get("path_id")
        if not provider_id or not path_id:
            continue
        if (provider_id, path_id) in seen:
            continue
        seen.add((provider_id, path_id))
        from services.interop.providers import get_provider
        provider = get_provider(provider_id)
        if provider is None:
            continue
        policy = _policy_from_observation(provider, observation)
        if not policy:
            continue
        result = await service.snapshot_policy(
            tenant_id, provider_id, path_id, policy,
        )
        emitted.extend(result.get("emitted_events", []))
    return emitted
