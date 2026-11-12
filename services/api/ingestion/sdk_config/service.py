"""
Aether Service — SDK Remote Config & Auto-Update

Provides signed manifest delivery, staged rollout orchestration, and rollback support.

Security model:
  - Manifests are signed with ECDSA P-256 (ES256) over a canonical JSON form; see
    manifest_signing.py and docs/reference/sdks/manifest-signing.md.
  - The signing key is derived deterministically from the SDK_CONFIG_SECRET env
    var, which never leaves the server. SDKs hold only the public key
    (scripts/sdk_manifest_public_key.py) and verify before applying a manifest.
  - Manifests are signed when delivered, so a rotated secret or an older stored
    version is never served with a stale signature.
  - Rollout gating uses a deterministic hash of (tenant_id + sdk_id) % 100 so
    the same SDK instance always gets the same rollout decision.

Manifest versioning:
  - Each publish appends an immutable durable version in PostgreSQL.
  - Active and previous pointers are durable; Redis is only a delivery cache.

Staged rollouts:
  - rollout_percentage (0–100) controls what fraction of SDK instances receive
    a new manifest version.
  - Instances outside the cohort continue receiving the stable manifest.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.common.common import BadRequestError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store
from ingestion.sdk_config import manifest_signing
from repositories.sdk_repos import SDKManifestStateRepository, SDKManifestVersionRepository

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
    signature: str = ""                       # base64url raw r||s, set by SDKConfigService._signed
    source: str = "tenant_published"
    publisher_id: str = "system"
    signature_alg: str = manifest_signing.SIGNATURE_ALG  # signed, so it cannot be downgraded

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────

class SDKConfigService:
    """
    Remote config lifecycle manager.

    Stores immutable manifests and active/previous pointers durably, with Redis
    used only as an expiring delivery cache.
    """

    def __init__(self) -> None:
        self._manifest_store = get_store("sdk_manifests")
        self._secret = os.getenv(_CONFIG_SECRET_ENV, "default-dev-secret-change-in-production")
        if os.getenv("AETHER_ENV", "local").lower() != "local" and self._secret == "default-dev-secret-change-in-production":
            raise RuntimeError(f"{_CONFIG_SECRET_ENV} must be a non-default secret outside local development")
        self._signing_key = manifest_signing.derive_private_key(self._secret)
        self._versions = SDKManifestVersionRepository()
        self._states = SDKManifestStateRepository()

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
        current_raw = await self._load_active(tenant_id)
        if current_raw is None:
            return None

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
                state = await self._states.get(tenant_id) or {}
                prev_raw = await self._versions.get_version(tenant_id, str(state.get("previous_version"))) if state.get("previous_version") else None
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
        return self._signed(manifest)

    async def get_active_manifest(self, tenant_id: str) -> Optional[SDKManifest]:
        """
        Return the tenant's current active manifest WITHOUT rollout gating.

        Used by the tenant settings UI (and other admin surfaces) which must
        always see the latest published manifest they are managing — never the
        cohort-gated view an individual SDK instance would receive. Returns
        ``None`` when the tenant has never published configuration.
        """
        current_raw = await self._load_active(tenant_id)
        if current_raw is None:
            return None
        return self._signed(SDKManifest(**{
            k: current_raw[k]
            for k in SDKManifest.__dataclass_fields__
            if k in current_raw
        }))

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
        state = await self._states.get(tenant_id) or {}
        current_raw = await self._load_active(tenant_id)

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
        manifest = self._signed(manifest)  # also rejects values that cannot be signed

        durable = {**manifest.to_dict(), "tenant_id": tenant_id, "deployment_state": "active"}
        await self._versions.create_version(durable)
        await self._states.upsert(tenant_id, {
            "active_version": new_version,
            "previous_version": state.get("active_version"),
            "updated_at": manifest.published_at,
        })

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
        state = await self._states.get(tenant_id) or {}
        previous_version = state.get("previous_version")
        prev_raw = await self._versions.get_version(tenant_id, str(previous_version)) if previous_version else None
        if prev_raw is None:
            return None

        # Swap previous → current (keep a copy of what was current in previous)
        current_raw = await self._load_active(tenant_id)
        if current_raw:
            await self._manifest_store.set(
                self._previous_key(tenant_id), current_raw, ttl_seconds=_MANIFEST_TTL_SECONDS * 24
            )

        await self._manifest_store.set(
            self._current_key(tenant_id), prev_raw, ttl_seconds=_MANIFEST_TTL_SECONDS * 24
        )
        await self._states.upsert(tenant_id, {
            "active_version": previous_version,
            "previous_version": state.get("active_version"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

        manifest = SDKManifest(**{
            k: prev_raw[k]
            for k in SDKManifest.__dataclass_fields__
            if k in prev_raw
        })

        logger.info(
            "sdk_config.manifest_rolled_back",
            extra={"tenant_id": tenant_id, "restored_version": manifest.manifest_version},
        )
        return self._signed(manifest)

    # ── Rollout Status ────────────────────────────────────────────────────

    async def get_rollout_status(self, tenant_id: str) -> dict[str, Any]:
        """Return rollout metadata for operator visibility."""
        state = await self._states.get(tenant_id) or {}
        current_raw = await self._load_active(tenant_id)
        prev_raw = await self._versions.get_version(tenant_id, str(state.get("previous_version"))) if state.get("previous_version") else None

        return {
            "tenant_id": tenant_id,
            "current_version": current_raw.get("manifest_version") if current_raw else None,
            "current_rollout_pct": current_raw.get("rollout_percentage") if current_raw else None,
            "previous_version": prev_raw.get("manifest_version") if prev_raw else None,
            "has_rollback_available": prev_raw is not None,
            "current_published_at": current_raw.get("published_at") if current_raw else None,
        }

    # ── Signing ───────────────────────────────────────────────────────────

    def public_key(self) -> str:
        """Base64url SPKI public key to configure in client SDKs."""
        return manifest_signing.public_key_spki_b64url(self._signing_key)

    def verify_manifest(self, manifest: SDKManifest) -> bool:
        """Verify a manifest against this service's public key (reference verifier)."""
        return manifest_signing.verify(self.public_key(), manifest.to_dict())

    def _signed(self, manifest: SDKManifest) -> SDKManifest:
        """Return the manifest with a fresh signature over its current contents."""
        manifest.signature_alg = manifest_signing.SIGNATURE_ALG
        try:
            manifest.signature = manifest_signing.sign(self._signing_key, manifest.to_dict())
        except manifest_signing.ManifestSigningError as exc:
            raise BadRequestError(f"manifest cannot be signed: {exc}") from exc
        return manifest

    async def _load_active(self, tenant_id: str) -> Optional[dict[str, Any]]:
        state = await self._states.get(tenant_id)
        if not state or not state.get("active_version"):
            return None
        durable = await self._versions.get_version(tenant_id, str(state["active_version"]))
        if durable:
            await self._manifest_store.set(self._current_key(tenant_id), durable, ttl_seconds=_MANIFEST_TTL_SECONDS)
        return durable

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
