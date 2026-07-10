"""Export manifest construction — the durable evidence attached to every artifact."""

from __future__ import annotations

import hashlib
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Repo root: manifest.py -> export -> services -> aether-backend -> "Backend Architecture" -> root
_REPO_ROOT = Path(__file__).resolve().parents[4]

_SENSITIVE_PARAM_TOKENS = ("secret", "token", "password", "key", "credential")


def _platform_version() -> str:
    try:
        with open(_REPO_ROOT / "pyproject.toml", "rb") as fh:
            return tomllib.load(fh)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


def sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Echo request params into the manifest with secret-like keys redacted."""
    clean: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if any(tok in key.lower() for tok in _SENSITIVE_PARAM_TOKENS):
            clean[key] = "[redacted]"
        else:
            clean[key] = value
    return clean


def build_manifest(
    content: bytes,
    *,
    export_type: str,
    tenant_id: str,
    params: dict[str, Any],
    correlation_id: Optional[str] = None,
    row_count: Optional[int] = None,
    columns: Optional[list[str]] = None,
    per_source: Optional[dict[str, int]] = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "export_type": export_type,
        "tenant_id": tenant_id,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator_version": _platform_version(),
        "params": sanitize_params(params),
    }
    if correlation_id:
        manifest["correlation_id"] = correlation_id
    if row_count is not None:
        manifest["row_count"] = row_count
    if columns:
        manifest["columns"] = columns
    if per_source:
        manifest["per_source"] = per_source
    return manifest
