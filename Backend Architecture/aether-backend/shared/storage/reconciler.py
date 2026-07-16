"""
Aether Shared — Storage Reconciler

Compares the descriptor index (hot metadata) against the object store
(payload bytes) and classifies every divergence:

  - missing objects:  a descriptor exists but its object is gone
  - orphan objects:   an object exists with no descriptor claiming it
  - checksum drift:   both exist but the object no longer hashes to the
                      descriptor's sha256 (corruption / tamper / overwrite)

``reconcile(...)`` is a PURE function over plain data (descriptors + a
key→sha256 mapping) so the detection logic is fully testable without S3.
``reconcile_object_store(...)`` is the thin IO wrapper that gathers both
sides from the live repository/object store, calls the pure core, and emits
metrics. The reconciler never mutates anything — it reports; remediation is
an operator decision (and object-backed Bronze lifecycle is FT-8's scope).

Runtime scheduling is gated by settings.storage_plane.reconciler_enabled
(STORAGE_RECONCILER_ENABLED, default OFF).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Union

from shared.logger.logger import get_logger, metrics
from shared.storage.descriptor import StorageDescriptor, sha256_hex
from shared.storage.object_store import ObjectNotFoundError, ObjectStore

logger = get_logger("aether.storage.reconciler")

DescriptorLike = Union[StorageDescriptor, Mapping[str, Any]]


@dataclass(frozen=True)
class ReconciliationReport:
    """Typed result of one reconciliation pass."""

    scanned_descriptors: int
    scanned_objects: int
    healthy: int
    missing_objects: tuple[str, ...]   # locators with a descriptor, no object
    orphan_objects: tuple[str, ...]    # object keys no descriptor claims
    checksum_drift: tuple[str, ...]    # locators whose bytes hash differently

    @property
    def is_clean(self) -> bool:
        return not (self.missing_objects or self.orphan_objects or self.checksum_drift)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_descriptors": self.scanned_descriptors,
            "scanned_objects": self.scanned_objects,
            "healthy": self.healthy,
            "missing_objects": list(self.missing_objects),
            "orphan_objects": list(self.orphan_objects),
            "checksum_drift": list(self.checksum_drift),
            "is_clean": self.is_clean,
        }


def _locator_and_checksum(descriptor: DescriptorLike) -> tuple[str, str]:
    if isinstance(descriptor, StorageDescriptor):
        return descriptor.locator, descriptor.checksum_sha256
    return (
        str(descriptor.get("locator", "")),
        str(descriptor.get("checksum_sha256", "")),
    )


def reconcile(
    descriptors: Sequence[DescriptorLike],
    object_checksums: Mapping[str, str],
) -> ReconciliationReport:
    """PURE reconciliation core — no IO, no S3, fully deterministic.

    Args:
        descriptors:      descriptor rows (StorageDescriptor or persisted dicts)
        object_checksums: key -> sha256 of the bytes actually in the store
    """
    missing: list[str] = []
    drift: list[str] = []
    healthy = 0
    claimed: set[str] = set()

    for descriptor in descriptors:
        locator, expected = _locator_and_checksum(descriptor)
        if not locator:
            continue
        claimed.add(locator)
        actual = object_checksums.get(locator)
        if actual is None:
            missing.append(locator)
        elif actual != expected:
            drift.append(locator)
        else:
            healthy += 1

    orphans = [key for key in object_checksums if key not in claimed]

    return ReconciliationReport(
        scanned_descriptors=len(descriptors),
        scanned_objects=len(object_checksums),
        healthy=healthy,
        missing_objects=tuple(sorted(missing)),
        orphan_objects=tuple(sorted(orphans)),
        checksum_drift=tuple(sorted(drift)),
    )


def _emit_report_metrics(report: ReconciliationReport) -> None:
    metrics.increment("storage_reconcile_run_total")
    if report.missing_objects:
        metrics.increment(
            "storage_reconcile_missing_object_total", len(report.missing_objects)
        )
    if report.orphan_objects:
        metrics.increment(
            "storage_reconcile_orphan_object_total", len(report.orphan_objects)
        )
    if report.checksum_drift:
        metrics.increment(
            "storage_reconcile_checksum_drift_total", len(report.checksum_drift)
        )


async def reconcile_object_store(
    descriptor_repo: Optional[Any] = None,
    object_store: Optional[ObjectStore] = None,
    *,
    tenant_id: Optional[str] = None,
    prefix: str = "",
    limit: int = 10_000,
    emit_metrics: bool = True,
) -> ReconciliationReport:
    """IO wrapper: gather descriptors + object checksums, run the pure core.

    Object checksums are computed by fetching each listed object once; a key
    that disappears between list() and get() counts as missing on the next
    pass rather than crashing this one.
    """
    if descriptor_repo is None:
        from repositories.repos import StorageDescriptorRepository  # lazy

        descriptor_repo = StorageDescriptorRepository()
    if object_store is None:
        from shared.storage.object_store import get_object_store  # lazy

        object_store = get_object_store()

    filters: dict[str, Any] = {}
    if tenant_id is not None:
        filters["tenant_id"] = tenant_id
    descriptors = await descriptor_repo.find_many(filters=filters or None, limit=limit)

    object_checksums: dict[str, str] = {}
    for key in object_store.list(prefix):
        try:
            object_checksums[key] = sha256_hex(object_store.get(key))
        except ObjectNotFoundError:
            continue  # raced a delete; the next pass classifies it

    report = reconcile(descriptors, object_checksums)
    if emit_metrics:
        _emit_report_metrics(report)
    if not report.is_clean:
        logger.warning(
            f"Storage reconciliation found drift: "
            f"missing={len(report.missing_objects)} "
            f"orphans={len(report.orphan_objects)} "
            f"checksum_drift={len(report.checksum_drift)}"
        )
    return report
