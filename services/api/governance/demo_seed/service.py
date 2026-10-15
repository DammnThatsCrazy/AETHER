from __future__ import annotations

import hashlib
import logging
import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Callable, Optional

from .dataset import v1_manifest
from .errors import SeedPolicyError, SeedSafetyError

logger = logging.getLogger("aether.demo_seed")
from .models import Clock, SeedManifest, SeedResult
from .policy import assert_seed_allowed
from .repositories import (
    ContinuationScopedSeedRepository,
    DurableStoreSeedRepository,
    SeedOwnershipRepository,
    SeedResetAuditRepository,
    SeedRunRepository,
    domain_repositories,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ownership_id(tenant_id: str, namespace: str, repository: str, record_id: str) -> str:
    value = f"{tenant_id}:{namespace}:{repository}:{record_id}".encode()
    return f"seed-own-{hashlib.sha256(value).hexdigest()[:32]}"


def _tenant_record_id(tenant_id: str, template_id: str) -> str:
    return str(uuid.uuid5(uuid.UUID("989a2072-6b37-5638-a65d-a0fc5d38c0da"), f"{tenant_id}:{template_id}"))


def _replace_template_ids(value: object, ids: dict[str, str]) -> object:
    if isinstance(value, str):
        return ids.get(value, value)
    if isinstance(value, list):
        return [_replace_template_ids(item, ids) for item in value]
    if isinstance(value, dict):
        return {key: _replace_template_ids(item, ids) for key, item in value.items()}
    return value


def _target_ids(manifest: SeedManifest, tenant_id: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in manifest.records:
        explicit = item.payload.get("_seed_target_id")
        if isinstance(explicit, str):
            result[item.record_id] = explicit.format(tenant_id=tenant_id)
        elif item.repository == "tenants":
            result[item.record_id] = tenant_id
        else:
            result[item.record_id] = _tenant_record_id(tenant_id, item.record_id)
    return result


def _identity_field(repository: str) -> Optional[str]:
    """The domain identity key stamped into each seeded row's payload.

    The repository's row carries ``id`` (the table/store primary key, stamped by
    insert) AND a domain-noun id alias so the API read paths that key on the
    domain id find the record. ``continuations`` uses ``id`` because the
    continuation context model's canonical identity field is ``id``.
    """
    return {
        "users": "user_id",
        "entities": "entity_id",
        "campaigns": "campaign_id",
        "economic_resources": "resource_id",
        "payment_intents": "intent_id",
        "settlement_events": "settlement_event_id",
        "alerts": "alert_id",
        "providers": "provider_id",
        "metering_evidence": "metered_event_id",
        "import_sessions": "import_id",
        "investigations": "investigation_id",
        "commerce_resources": "resource_id",
        "commerce_policies": "policy_id",
        "commerce_facilitators": "facilitator_id",
        "commerce_approvals": "approval_id",
        "commerce_settlements": "settlement_id",
        "commerce_entitlements": "entitlement_id",
        "notifications": "notification_id",
        "continuations": "id",
        "exceptions": "exception_id",
        "incidents": "incident_id",
        "runs": "run_id",
        "reviews": "batch_id",
    }.get(repository)


class DemoSeedService:
    """Explicit seed/reset orchestration over the normal backend repositories."""

    def __init__(
        self,
        *,
        environment: str | None = None,
        clock: Clock = _utc_now,
        run_id_factory: Callable[[], str] | None = None,
        manifest_factory: Callable[[str], SeedManifest] = v1_manifest,
    ) -> None:
        configured_environment = environment or os.getenv("AETHER_ENV")
        if not configured_environment:
            raise SeedPolicyError("AETHER_ENV must be explicitly configured")
        self.environment = configured_environment
        self.clock = clock
        self.run_id_factory = run_id_factory or (lambda: str(uuid.uuid4()))
        self.manifest_factory = manifest_factory
        self.repositories = domain_repositories()
        self.runs = SeedRunRepository()
        self.ownership = SeedOwnershipRepository()
        self.reset_audit = SeedResetAuditRepository()

    def _resolve_repository(self, repository_name: str, tenant_id: str):
        """Resolve the repository for one seed record, binding tenant context.

        Most domains live in ``self.repositories`` (BaseRepository-shaped). The
        continuation plane is tenant-scope-scoped and cannot resolve a scope
        from an id alone, so it is resolved here with the tenant bound to the
        canonical ``ContinuationRepository`` — seeding reuses its scope +
        idempotency semantics rather than writing past them.
        """
        if repository_name == "continuations":
            return ContinuationScopedSeedRepository(tenant_scope=f"t:{tenant_id}")
        try:
            return self.repositories[repository_name]
        except KeyError:
            raise KeyError(
                f"no repository registered for demo-seed domain {repository_name!r}"
            ) from None

    async def seed(
        self,
        *,
        tenant_id: str,
        namespace: str,
        actor: str = "demo-seed-cli",
    ) -> SeedResult:
        assert_seed_allowed(environment=self.environment, tenant_id=tenant_id)
        if not tenant_id.strip() or not namespace.strip():
            raise SeedSafetyError("tenant_id and namespace are required")

        manifest = self.manifest_factory(namespace)
        run_id = self.run_id_factory()
        started = self.clock()
        result = SeedResult(
            seed_run_id=run_id,
            tenant_id=tenant_id,
            namespace=namespace,
            version=manifest.version,
            checksum=manifest.checksum,
            status="running",
        )
        await self.runs.insert(run_id, {
            **result.to_dict(),
            "actor": actor,
            "command_source": actor,
            "started_at": started.isoformat(),
            "completed_at": None,
            "error_summary": None,
        })

        try:
            target_ids = _target_ids(manifest, tenant_id)
            for item in manifest.records:
                repository = self._resolve_repository(item.repository, tenant_id)
                target_id = target_ids[item.record_id]
                owner_id = _ownership_id(
                    tenant_id, namespace, item.repository, target_id,
                )
                owned = await self.ownership.find_by_id(owner_id)
                existing = await repository.find_by_id(target_id)

                if owned is not None:
                    if (
                        owned.get("tenant_id") != tenant_id
                        or owned.get("seed_namespace") != namespace
                        or owned.get("record_id") != target_id
                    ):
                        raise SeedSafetyError(f"ownership sidecar mismatch for {target_id}")
                    if existing is not None:
                        result.skipped[item.domain] = result.skipped.get(item.domain, 0) + 1
                        continue
                    if isinstance(repository, DurableStoreSeedRepository):
                        # M8-C1: the ownership ledger is authoritative for durable
                        # domains. The sidecar exists but the record is absent
                        # (a fresh process with an empty process-local store, or a
                        # flushed cache) — this record was already seeded; count it
                        # skipped rather than writing a parallel copy or tripping
                        # the process-local guard.
                        result.skipped[item.domain] = result.skipped.get(item.domain, 0) + 1
                        continue
                elif existing is not None:
                    raise SeedSafetyError(
                        f"refusing to overwrite non-seeded {item.repository} record {target_id}"
                    )

                observed_at = started.timestamp() + item.offset_seconds
                provenance = {
                    "data_origin": "synthetic_seed",
                    "seed_namespace": namespace,
                    "seed_version": manifest.version,
                    "seed_run_id": run_id,
                    "demo_tenant_id": tenant_id,
                    "seed_created_at": started.isoformat(),
                    "source_domain": item.domain,
                }
                rendered_payload = _replace_template_ids(item.payload, target_ids)
                assert isinstance(rendered_payload, dict)
                rendered_payload.pop("_seed_target_id", None)
                time_offsets = rendered_payload.pop("_time_offsets", {})
                if isinstance(time_offsets, dict):
                    for field, offset in time_offsets.items():
                        rendered_payload[field] = datetime.fromtimestamp(
                            started.timestamp() + int(offset), tz=timezone.utc,
                        ).isoformat()
                payload = {
                    **rendered_payload,
                    "tenant_id": tenant_id,
                    "observed_at": datetime.fromtimestamp(
                        observed_at, tz=timezone.utc,
                    ).isoformat(),
                    "data_origin": "synthetic_seed",
                    "seed_provenance": provenance,
                }
                identity_field = _identity_field(item.repository)
                if identity_field:
                    payload[identity_field] = target_id

                await repository.insert(target_id, payload)
                await self.ownership.insert(owner_id, {
                    "tenant_id": tenant_id,
                    "seed_namespace": namespace,
                    "seed_version": manifest.version,
                    "seed_run_id": run_id,
                    "repository": item.repository,
                    "record_id": target_id,
                    "source_domain": item.domain,
                    "created_at_from_seed_clock": started.isoformat(),
                })
                result.inserted[item.domain] = result.inserted.get(item.domain, 0) + 1

            result.status = "completed"
        except Exception as exc:
            result.status = "failed"
            result.errors.append(str(exc))
            await self.runs.update(run_id, {
                **result.to_dict(),
                "completed_at": self.clock().isoformat(),
                "error_summary": str(exc),
            })
            raise

        await self.runs.update(run_id, {
            **result.to_dict(),
            "completed_at": self.clock().isoformat(),
            "error_summary": None,
        })
        return result

    async def status(
        self, *, tenant_id: str, namespace: str,
    ) -> dict:
        manifest = self.manifest_factory(namespace)
        runs = await self.runs.find_many(
            filters={"tenant_id": tenant_id, "namespace": namespace},
            limit=100,
        )
        tenant = await self.repositories["tenants"].find_by_id(tenant_id)
        latest = runs[0] if runs else None
        latest_run = None
        if latest is not None:
            latest_run = {
                "seed_run_id": latest.get("seed_run_id") or latest.get("id"),
                "dataset_version": latest.get("version"),
                "namespace": latest.get("namespace"),
                "tenant_id": latest.get("tenant_id"),
                "checksum": latest.get("checksum"),
                "status": latest.get("status"),
                "started_at": latest.get("started_at"),
                "completed_at": latest.get("completed_at"),
                "inserted_counts": latest.get("inserted", {}),
                "updated_counts": latest.get("updated", {}),
                "skipped_counts": latest.get("skipped", {}),
            }
        # M8-C3: never derive seeded-ness from the ownership sidecars alone.
        # Count records ACTUALLY present through the same canonical read paths
        # verify() uses, and count as owned only records that are both
        # sidecar-owned AND present. A fresh process with an empty process-local
        # DurableStore therefore reports the durable runs/reviews domains
        # truthfully as not seeded, even though their sidecars persist.
        present = 0
        owned_and_present = 0
        target_ids = _target_ids(manifest, tenant_id)
        for item in manifest.records:
            target_id = target_ids[item.record_id]
            owner = await self.ownership.find_by_id(
                _ownership_id(tenant_id, namespace, item.repository, target_id),
            )
            try:
                record = await self._resolve_repository(
                    item.repository, tenant_id,
                ).find_by_id(target_id)
            except Exception as exc:
                # A repository that cannot be read for a status check must not
                # fail the whole status surface — count it as not seeded.
                logger.warning(
                    "demo_seed status read failed repository=%s target=%s: %s",
                    item.repository, target_id, exc,
                )
                record = None
            if record is not None:
                present += 1
                if owner is not None:
                    owned_and_present += 1

        durable_repos = [
            repo
            for repo in self.repositories.values()
            if isinstance(repo, DurableStoreSeedRepository)
        ]
        durable_store_shared = (
            bool(durable_repos)
            and all(not repo.is_process_local for repo in durable_repos)
        )

        return {
            "seeded": present == len(manifest.records) and tenant is not None,
            "is_demo_tenant": bool(tenant and tenant.get("is_demo_tenant")),
            "tenant_id": tenant_id,
            "tenant_name": tenant.get("name") if tenant else None,
            "data_origin": tenant.get("data_origin") if tenant else None,
            "namespace": namespace,
            "dataset_version": manifest.version,
            "checksum": manifest.checksum,
            "run_count": len(runs),
            "owned_record_count": owned_and_present,
            "durable_store_shared": durable_store_shared,
            "latest_run": latest_run,
        }

    async def verify(self, *, tenant_id: str, namespace: str) -> dict:
        manifest = self.manifest_factory(namespace)
        failures: list[str] = []
        verified = Counter()
        target_ids = _target_ids(manifest, tenant_id)
        for item in manifest.records:
            target_id = target_ids[item.record_id]
            owner_id = _ownership_id(tenant_id, namespace, item.repository, target_id)
            owner = await self.ownership.find_by_id(owner_id)
            record = await self._resolve_repository(item.repository, tenant_id).find_by_id(target_id)
            if owner is None or record is None:
                failures.append(f"missing {item.repository}:{target_id}")
                continue
            provenance = record.get("seed_provenance") or {}
            if (
                record.get("tenant_id") != tenant_id
                or provenance.get("demo_tenant_id") != tenant_id
                or provenance.get("seed_namespace") != namespace
                or provenance.get("seed_version") != manifest.version
                or provenance.get("data_origin") != "synthetic_seed"
            ):
                failures.append(f"provenance mismatch {item.repository}:{target_id}")
                continue
            verified[item.domain] += 1
        return {
            "ok": not failures,
            "tenant_id": tenant_id,
            "namespace": namespace,
            "version": manifest.version,
            "checksum": manifest.checksum,
            "verified": dict(verified),
            "failures": failures,
        }

    async def reset(
        self,
        *,
        tenant_id: str,
        namespace: str,
        confirmation: str,
        actor: str = "demo-reset-cli",
    ) -> dict:
        assert_seed_allowed(environment=self.environment, tenant_id=tenant_id)
        expected = f"RESET {tenant_id} {namespace}"
        if confirmation != expected:
            raise SeedSafetyError(f"confirmation must exactly equal {expected!r}")

        owners = await self.ownership.find_many(
            filters={"tenant_id": tenant_id, "seed_namespace": namespace},
            limit=10_000,
        )
        deleted = Counter()
        refused: list[str] = []
        for owner in owners:
            repository_name = str(owner["repository"])
            record_id = str(owner["record_id"])
            try:
                repository = self._resolve_repository(repository_name, tenant_id)
            except KeyError:
                refused.append(f"unknown repository {repository_name}:{record_id}")
                continue
            record = await repository.find_by_id(record_id)
            if record is not None:
                provenance = record.get("seed_provenance") or {}
                if (
                    record.get("tenant_id") != tenant_id
                    or provenance.get("demo_tenant_id") != tenant_id
                    or provenance.get("seed_namespace") != namespace
                    or provenance.get("data_origin") != "synthetic_seed"
                ):
                    refused.append(f"ownership/provenance mismatch {repository_name}:{record_id}")
                    continue
                await repository.delete(record_id)
                deleted[str(owner.get("source_domain", repository_name))] += 1
            await self.ownership.delete(str(owner["id"]))

        audit_id = self.run_id_factory()
        audit = await self.reset_audit.insert(audit_id, {
            "tenant_id": tenant_id,
            "seed_namespace": namespace,
            "actor": actor,
            "action": "demo_seed_reset",
            "deleted": dict(deleted),
            "refused": refused,
            "completed_at": self.clock().isoformat(),
            "cross_tenant_records_removed": 0,
        })
        if refused:
            raise SeedSafetyError(
                "reset stopped with protected records: " + "; ".join(refused)
            )
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "namespace": namespace,
            "deleted": dict(deleted),
            "audit_id": audit["id"],
            "cross_tenant_records_removed": 0,
        }


__all__ = [
    "DemoSeedService",
    "SeedPolicyError",
    "SeedSafetyError",
]
