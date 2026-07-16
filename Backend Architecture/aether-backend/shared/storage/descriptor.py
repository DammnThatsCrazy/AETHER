"""
Aether Shared — Universal Storage Descriptor

The StorageDescriptor is the canonical, immutable handle for any object the
Elastic Data Plane externalizes out of the hot database path (packed Bronze
segments, historical exports, compacted fact windows, ...). Everything a
consumer needs to locate, verify, and interpret the object travels on the
descriptor; the object itself is opaque bytes in the object store.

Descriptors are persisted through repositories.repos.StorageDescriptorRepository
(BaseRepository shape: id TEXT PK, data JSONB, tenant_id, created_at/updated_at)
so they are queryable metadata even when payloads live in S3.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from shared.common.common import utc_now

DESCRIPTOR_SCHEMA_VERSION = 1


def sha256_hex(data: bytes) -> str:
    """Canonical checksum used on every externalized object."""
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class StorageDescriptor:
    """Immutable handle for one externalized object.

    Fields:
        descriptor_id:   stable unique id (primary key in the descriptor table)
        resource_type:   persistent resource type — must have a policy in
                         config/storage_policies.yaml
        tenant_id:       owning tenant ("" only for platform-scoped objects)
        locator:         object-store key the payload lives under
        codec:           codec ACTUALLY applied to the stored bytes
                         (zstd | gzip | none — gzip is the local fallback when
                         the zstd module is unavailable)
        format:          logical payload format (jsonl | row | bytes)
        checksum_sha256: sha256 of the stored (post-codec) bytes; verified on
                         every hydrate
        size_bytes:      size of the stored bytes
        record_count:    logical records inside the object (0 for raw bytes)
        lineage:         source record/object ids this object derives from
        created_at:      ISO-8601 creation timestamp
        schema_version:  descriptor schema version (for forward migration)
    """

    resource_type: str
    tenant_id: str
    locator: str
    codec: str
    format: str
    checksum_sha256: str
    size_bytes: int
    record_count: int
    lineage: tuple[str, ...] = ()
    created_at: str = ""
    schema_version: int = DESCRIPTOR_SCHEMA_VERSION
    descriptor_id: str = ""

    def __post_init__(self) -> None:
        if not self.resource_type:
            raise ValueError("StorageDescriptor.resource_type is required")
        if not self.locator:
            raise ValueError("StorageDescriptor.locator is required")
        if not self.checksum_sha256:
            raise ValueError("StorageDescriptor.checksum_sha256 is required")
        # Normalize mutable/list lineage into a tuple so the frozen dataclass
        # stays hashable and round-trips through JSON cleanly.
        if not isinstance(self.lineage, tuple):
            object.__setattr__(self, "lineage", tuple(self.lineage))
        if not self.created_at:
            object.__setattr__(self, "created_at", utc_now().isoformat())
        if not self.descriptor_id:
            object.__setattr__(self, "descriptor_id", f"sd_{uuid.uuid4().hex}")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["lineage"] = list(self.lineage)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StorageDescriptor":
        """Rebuild a descriptor from its persisted JSONB dict.

        Repository rows carry extra bookkeeping keys (id, created_at/updated_at
        stamps from BaseRepository.insert) — only descriptor fields are read.
        """
        return cls(
            resource_type=str(data.get("resource_type", "")),
            tenant_id=str(data.get("tenant_id", "")),
            locator=str(data.get("locator", "")),
            codec=str(data.get("codec", "none")),
            format=str(data.get("format", "bytes")),
            checksum_sha256=str(data.get("checksum_sha256", "")),
            size_bytes=int(data.get("size_bytes", 0)),
            record_count=int(data.get("record_count", 0)),
            lineage=tuple(data.get("lineage") or ()),
            created_at=str(data.get("created_at", "")),
            schema_version=int(data.get("schema_version", DESCRIPTOR_SCHEMA_VERSION)),
            descriptor_id=str(data.get("descriptor_id", "")),
        )
