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
