#!/usr/bin/env python3
"""Generate ``docs/_generated/financial-capability-matrix.json``.

The financial capability matrix is projected from the live certification
registry and cross-checked against the release manifest, route registry,
service classification, deployment profiles, data-rights vocabulary, and
canonical event vocabularies. It is generated — never hand-maintained — so a
route, release, rights, or provider change cannot silently leave an unsupported
capability claim behind.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_ROOT = ROOT / "services" / "api"
OUTPUT = ROOT / "docs" / "_generated" / "financial-capability-matrix.json"


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def main() -> int:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    try:
        from shared.certification.capability_records import (
            build_financial_capability_matrix,
        )
        from shared.certification.registry import import_errors, iter_financial_descriptors
    except Exception as exc:  # pragma: no cover - surfaces a real wiring break
        print(f"error: could not import financial capability registry: {exc}", file=sys.stderr)
        return 1

    release_manifest = yaml.safe_load(
        (ROOT / "config" / "founding_tenant_release.yaml").read_text(encoding="utf-8")
    )
    matrix = build_financial_capability_matrix(
        iter_financial_descriptors(),
        release_manifest=release_manifest if isinstance(release_manifest, dict) else {},
    )
    payload = {
        "version": read_version(),
        "generated_from": "services/api/shared/certification/capability_records.py",
        **matrix,
    }
    payload["summary"]["import_errors"] = import_errors()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = payload["summary"]
    print(
        f"extract_financial_capability: wrote {OUTPUT.relative_to(ROOT)} "
        f"({summary['total']} records across {summary['domains']} domains; "
        f"production_eligible={summary['production_eligible']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
