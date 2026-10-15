from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass(frozen=True)
class SeedRecord:
    domain: str
    repository: str
    logical_name: str
    record_id: str
    offset_seconds: int
    payload: dict[str, Any]


@dataclass(frozen=True)
class SeedManifest:
    version: str
    namespace: str
    checksum: str
    records: tuple[SeedRecord, ...]


@dataclass
class SeedResult:
    seed_run_id: str
    tenant_id: str
    namespace: str
    version: str
    checksum: str
    status: str
    inserted: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_run_id": self.seed_run_id,
            "tenant_id": self.tenant_id,
            "namespace": self.namespace,
            "version": self.version,
            "checksum": self.checksum,
            "status": self.status,
            "inserted": dict(self.inserted),
            "updated": {},
            "skipped": dict(self.skipped),
            "errors": list(self.errors),
        }


Clock = Callable[[], datetime]
