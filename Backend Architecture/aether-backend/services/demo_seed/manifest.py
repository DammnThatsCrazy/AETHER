from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Iterable

from .models import SeedManifest, SeedRecord

DATASET_VERSION = "v1"
DEFAULT_NAMESPACE = "aether-demo-v1"
_ID_NAMESPACE = uuid.UUID("de89db68-4242-55a4-a771-a1e7b682bd14")


def stable_id(namespace: str, domain: str, logical_name: str) -> str:
    """Return the stable identifier for one logical demonstration record."""
    return str(uuid.uuid5(_ID_NAMESPACE, f"{namespace}:{domain}:{logical_name}"))


def _canonical_record(record: SeedRecord) -> dict[str, Any]:
    # The checksum deliberately covers offsets, not rendered wall-clock
    # timestamps. Re-seeding tomorrow therefore verifies against the same
    # versioned dataset checksum.
    return {
        "domain": record.domain,
        "repository": record.repository,
        "logical_name": record.logical_name,
        "record_id": record.record_id,
        "offset_seconds": record.offset_seconds,
        "payload": record.payload,
    }


def build_manifest(
    records: Iterable[SeedRecord],
    *,
    namespace: str = DEFAULT_NAMESPACE,
    version: str = DATASET_VERSION,
) -> SeedManifest:
    ordered = tuple(sorted(records, key=lambda item: (item.domain, item.logical_name)))
    encoded = json.dumps(
        {
            "version": version,
            "namespace": namespace,
            "records": [_canonical_record(record) for record in ordered],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return SeedManifest(
        version=version,
        namespace=namespace,
        checksum=hashlib.sha256(encoded).hexdigest(),
        records=ordered,
    )
