"""Metering evidence service (§3.16).

New, additive service. Wires nothing into the app itself — see ``routes.py``
for the optional read-only router.
"""
from __future__ import annotations

from .service import (
    EXCLUDED_DUPLICATE,
    MeteredEvent,
    MeteringEvidenceRepository,
    MeteringEvidenceService,
)

__all__ = [
    "EXCLUDED_DUPLICATE",
    "MeteredEvent",
    "MeteringEvidenceRepository",
    "MeteringEvidenceService",
]
