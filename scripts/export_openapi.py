#!/usr/bin/env python3
"""Export the backend OpenAPI schema to a file.

FastAPI serves the live schema at ``/openapi.json``; this script snapshots it for
docs/contract review. Run with default (all feature flags off) for a stable
baseline.

Usage:
  python scripts/export_openapi.py [output.json]   # default: docs/_generated/openapi.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "docs/_generated/openapi.json")
    os.environ.setdefault("AETHER_ENV", "local")
    os.environ.setdefault("JWT_SECRET", "export-openapi")
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        from main import app  # noqa: WPS433 (import after sys.path setup)
    except Exception as exc:  # pragma: no cover - tool resilience
        print(f"error: could not import backend app: {exc}", file=sys.stderr)
        return 1
    try:
        schema = app.openapi()
    except Exception as exc:  # pragma: no cover
        print(f"error: could not build OpenAPI schema: {exc}", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    paths = len(schema.get("paths", {}))
    print(f"export_openapi: wrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out} ({paths} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
