"""
Aether Service — SDK Remote Config & Auto-Update

Provides signed manifest delivery, staged rollout orchestration, and rollback support.

Security model:
  - Manifests are signed with HMAC-SHA256 using the SDK_CONFIG_SECRET env var.
  - SDKs verify the signature before applying any manifest.
  - Rollout gating uses a deterministic hash of (tenant_id + sdk_id) % 100 so
    the same SDK instance always gets the same rollout decision.

Manifest versioning:
  - Each publish increments the semantic version stored in Redis.
  - The previous manifest is retained under a "previous" key for rollback.

Staged rollouts:
  - rollout_percentage (0–100) controls what fraction of SDK instances receive
    a new manifest version.
  - Instances outside the cohort continue receiving the stable manifest.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from shared.store import get_store

logger = get_logger("aether.service.sdk_config")

_MANIFEST_TTL_SECONDS = 3_600   # 1 h — SDKs re-fetch on expiry
_CONFIG_SECRET_ENV = "SDK_CONFIG_SECRET"


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SDKManifest:
    """Signed remote configuration manifest delivered to SDK instances."""
    manifest_version: str = "1"
    min_sdk_version: str = "6.0.0"
    schema_version: str = "7.0.0"
    rollout_percentage: int = 100             # 0–100 % of instances to deliver to
    features: dict[str, bool] = field(default_factory=dict)
    endpoints: dict[str, str] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)
    published_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    signature: str = ""                       # HMAC-SHA256 over canonical payload

    def canonical_payload(self) -> str:
        """Deterministic JSON string used for HMAC signing (excludes signature field)."""
        data = {
            "manifest_version": self.manifest_version,
            "min_sdk_version": self.min_sdk_version,
            "schema_version": self.schema_version,
            "rollout_percentage": self.rollout_percentage,
            "features": self.features,
            "endpoints": self.endpoints,
            "flags": self.flags,
            "published_at": self.published_at,
        }
        return json.dumps(data, sort_keys=True)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────

class SDKConfigService:
    """
    Remote config lifecycle manager.

    Stores manifests in Redis; uses a "current" and "previous" slot per tenant.
    """

    def __init__(self) -> None:
        self._manifest_store = get_store("sdk_manifests")
        self._secret = os.getenv(_CONFIG_SECRET_ENV, "default-dev-secret-change-in-production")

    # ── Manifest Delivery ─────────────────────────────────────────────────

    async def get_manifest(
        self,
        tenant_id: str,
        sdk_id: str,
        sdk_version: str = "",
        cohort: str = "default",
    ) -> Optional[SDKManifest]:
        """
        Return the active manifest for an SDK instance.

        Rollout gating: uses hash(tenant_id + sdk_id) % 100.
        If the instance falls outside the rollout percentage, returns the stable
        (previous) manifest instead of the canary.
        """
        current_raw = await self._manifest_store.get(self._current_key(tenant_id))
        if current_raw is None:
            # No manifest published — return default
            return self._default_manifest()

        manifest = SDKManifest(**{
            k: current_raw[k]
            for k in SDKManifest.__dataclass_fields__
            if k in current_raw
        })

        # Apply rollout gating
        if manifest.rollout_percentage < 100:
            cohort_bucket = self._cohort_bucket(tenant_id, sdk_id)
            if cohort_bucket >= manifest.rollout_percentage:
                # This instance is outside the rollout — serve previous stable manifest
                prev_raw = await self._manifest_store.get(self._previous_key(tenant_id))
                if prev_raw:
                    manifest = SDKManifest(**{
                        k: prev_raw[k]
                        for k in SDKManifest.__dataclass_fields__
                        if k in prev_raw
                    })

        metrics.increment(
            "aether_sdk_manifest_requests_total",
            labels={"tenant_id": tenant_id, "sdk_version": sdk_version or "unknown"},
        )
        return manifest

    # ── Manifest Publishing ───────────────────────────────────────────────

    async def publish_manifest(
        self,
        tenant_id: str,
        min_sdk_version: str,
        schema_version: str,
        features: dict[str, bool],
        endpoints: dict[str, str],
        flags: dict[str, Any],
        rollout_percentage: int = 100,
    ) -> SDKManifest:
        """
        Publish a new signed manifest version.

        The current manifest is demoted to "previous" for rollback support.
        """
        # Demote current → previous
        current_raw = await self._manifest_store.get(self._current_key(tenant_id))
        if current_raw:
            await self._manifest_store.set(
                self._previous_key(tenant_id), current_raw, ttl_seconds=_MANIFEST_TTL_SECONDS * 24
            )

        # Compute new version
        prev_version = int(current_raw.get("manifest_version", "0")) if current_raw else 0
        new_version = str(prev_version + 1)

        manifest = SDKManifest(
            manifest_version=new_version,
            min_sdk_version=min_sdk_version,
            schema_version=schema_version,
            rollout_percentage=max(0, min(100, rollout_percentage)),
            features=features,
            endpoints=endpoints,
            flags=flags,
        )
        manifest.signature = self._sign(manifest.canonical_payload())

        await self._manifest_store.set(
            self._current_key(tenant_id),
            manifest.to_dict(),
            ttl_seconds=_MANIFEST_TTL_SECONDS * 24,
        )

        metrics.increment(
            "aether_sdk_manifest_published_total",
            labels={"tenant_id": tenant_id},
        )
        metrics.observe(
            "aether_sdk_rollout_adoption_ratio",
            float(rollout_percentage) / 100.0,
            labels={"tenant_id": tenant_id},
        )

        # Publish Kafka event
        await self._publish_config_event(tenant_id, manifest)

        logger.info(
            "sdk_config.manifest_published",
            extra={
                "tenant_id": tenant_id,
                "version": new_version,
                "rollout_percentage": rollout_percentage,
            },
        )
        return manifest

    # ── Rollback ─────────────────────────────────────────────────────────

    async def rollback_manifest(self, tenant_id: str) -> Optional[SDKManifest]:
        """Restore the previous manifest as the active version."""
        prev_raw = await self._manifest_store.get(self._previous_key(tenant_id))
        if prev_raw is None:
            return None

        # Swap previous → current (keep a copy of what was current in previous)
        current_raw = await self._manifest_store.get(self._current_key(tenant_id))
        if current_raw:
            await self._manifest_store.set(
                self._previous_key(tenant_id), current_raw, ttl_seconds=_MANIFEST_TTL_SECONDS * 24
            )

        await self._manifest_store.set(
            self._current_key(tenant_id), prev_raw, ttl_seconds=_MANIFEST_TTL_SECONDS * 24
        )

        manifest = SDKManifest(**{
            k: prev_raw[k]
            for k in SDKManifest.__dataclass_fields__
            if k in prev_raw
        })

        logger.info(
            "sdk_config.manifest_rolled_back",
            extra={"tenant_id": tenant_id, "restored_version": manifest.manifest_version},
        )
        return manifest

    # ── Rollout Status ────────────────────────────────────────────────────

    async def get_rollout_status(self, tenant_id: str) -> dict[str, Any]:
        """Return rollout metadata for operator visibility."""
        current_raw = await self._manifest_store.get(self._current_key(tenant_id))
        prev_raw = await self._manifest_store.get(self._previous_key(tenant_id))

        return {
            "tenant_id": tenant_id,
            "current_version": current_raw.get("manifest_version") if current_raw else None,
            "current_rollout_pct": current_raw.get("rollout_percentage") if current_raw else None,
            "previous_version": prev_raw.get("manifest_version") if prev_raw else None,
            "has_rollback_available": prev_raw is not None,
            "current_published_at": current_raw.get("published_at") if current_raw else None,
        }

    # ── Signature Verification ────────────────────────────────────────────

    def verify_signature(self, canonical_payload: str, signature: str) -> bool:
        """Verify a manifest signature. Used by SDK-side verification logic."""
        expected = self._sign(canonical_payload)
        return hmac.compare_digest(expected, signature)

    # ── Internal Helpers ──────────────────────────────────────────────────

    def _sign(self, payload: str) -> str:
        return hmac.new(
            self._secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _cohort_bucket(tenant_id: str, sdk_id: str) -> int:
        """Deterministic 0–99 bucket for rollout gating."""
        digest = hashlib.md5(f"{tenant_id}:{sdk_id}".encode()).hexdigest()
        return int(digest[:4], 16) % 100

    @staticmethod
    def _current_key(tenant_id: str) -> str:
        return f"manifest:current:{tenant_id}"

    @staticmethod
    def _previous_key(tenant_id: str) -> str:
        return f"manifest:previous:{tenant_id}"

    @staticmethod
    def _default_manifest() -> SDKManifest:
        return SDKManifest(
            manifest_version="0",
            features={"analytics": True, "web3": True, "commerce": True},
            endpoints={},
            flags={"heartbeat_interval_seconds": 60},
        )

    async def _publish_config_event(self, tenant_id: str, manifest: SDKManifest) -> None:
        try:
            from shared.events.events import EventProducer, Event, Topic
            producer = EventProducer()
            event = Event(
                event_id=str(uuid.uuid4()),
                topic=Topic.SDK_CONFIG_UPDATED,
                version="1.0",
                tenant_id=tenant_id,
                source_service="sdk_config",
                payload={
                    "manifest_version": manifest.manifest_version,
                    "rollout_percentage": manifest.rollout_percentage,
                    "schema_version": manifest.schema_version,
                },
            )
            await producer.publish(event)
        except Exception as exc:
            logger.debug(f"SDK config Kafka publish skipped: {exc}")


# Module-level singleton
_sdk_config_service: Optional[SDKConfigService] = None


def get_sdk_config_service() -> SDKConfigService:
    global _sdk_config_service
    if _sdk_config_service is None:
        _sdk_config_service = SDKConfigService()
    return _sdk_config_service
