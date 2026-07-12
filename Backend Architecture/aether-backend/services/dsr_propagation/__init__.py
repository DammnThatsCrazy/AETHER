"""Backend DSR propagation-record layer (prompt §3.11 + §3.12).

This package is the backend-side *propagation record* + *impact index* layer for
Data Subject Requests. It does NOT execute erasure/access itself — the existing
`services/consent` DSR endpoint and the separate `aether-compliance` DSR engine
drive it. Its job is to give the backend a unified, tenant-scoped, fail-closed
record of *what a DSR touched* across every backend component, plus reverse
indexes (subject -> records, subject -> artifacts) for impact discovery.

Additive only: nothing here is wired into `main.py`. The optional read-only
router lives in `routes.py` (`APIRouter(prefix="/v1/dsr")`, variable ``router``)
for the integrator to mount.
"""

from __future__ import annotations

from .indexes import (
    ArtifactIndex,
    DSRArtifactIndexRepository,
    DSRSubjectIndexRepository,
    SubjectIndex,
)
from .models import (
    DSR_COMPONENTS,
    DSR_PROPAGATION_STATUSES,
    DSR_TERMINAL_STATUSES,
    DSR_TYPES,
    DSRComponent,
    DSROverallStatus,
    DSRPropagationStatus,
    DSRPropagationStep,
    DSRType,
    overall_status,
)
from .service import DSRPropagationRepository, DSRPropagationService

__all__ = [
    "ArtifactIndex",
    "DSRArtifactIndexRepository",
    "DSRSubjectIndexRepository",
    "SubjectIndex",
    "DSR_COMPONENTS",
    "DSR_PROPAGATION_STATUSES",
    "DSR_TERMINAL_STATUSES",
    "DSR_TYPES",
    "DSRComponent",
    "DSROverallStatus",
    "DSRPropagationStatus",
    "DSRPropagationStep",
    "DSRType",
    "overall_status",
    "DSRPropagationRepository",
    "DSRPropagationService",
]
