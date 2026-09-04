"""Projection digest (A8 projection engine).

A projection digest is a deterministic sha256 over the CANONICAL serialization
of a projection result's content — projection id, tenant id, subject, as-of,
sections, claims, dependency state, lens ids and temporal mode. ``generatedAt``
and ``page`` are deliberately excluded: a digest must be stable across reruns
of the same content (a timestamp or cursor would break reproducibility), which
is what makes a digest useful for cache-keying and drift detection.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical_json(payload: Any) -> str:
    """Sort-keyed, minimal-separator JSON (deterministic byte-for-byte)."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def compute_projection_digest(
    *,
    projection_id: str,
    tenant_id: str,
    subject: dict,
    as_of: str | None,
    sections: list[dict],
    claims: list[dict],
    dependency_state: list[dict],
    lens_ids: list[str] | None,
    temporal_mode: str | None,
) -> str:
    """The deterministic content digest for a projection result."""
    payload = {
        "projectionId": projection_id,
        "tenantId": tenant_id,
        "subject": subject,
        "asOf": as_of,
        "sections": sections,
        "claims": claims,
        "dependencyState": dependency_state,
        "lensIds": lens_ids or [],
        "temporalMode": temporal_mode,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_json(payload: Any) -> str:
    """Expose the canonical serialization (tests, cache keys)."""
    return _canonical_json(payload)


__all__ = ["canonical_json", "compute_projection_digest"]
