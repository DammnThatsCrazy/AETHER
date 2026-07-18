#!/usr/bin/env python3
"""Generate ``docs/_generated/adapter-certification-matrix.json`` from the
credentialless certification registry.

The provider capability/certification matrix is generated from source — never
hand-maintained — so provider readiness claims stay honest. The canonical
source of truth is::

    Backend Architecture/aether-backend/shared/certification/registry.py

Each first-release provider adapter's declared implementation status is resolved
to a ``CredentialReadiness`` state directly from the domain adapters, so the
matrix always reflects the code (e.g. interop scaffolds show ``scaffolded``, not
an optimistic hand-typed value).

Determinism: ``build_capability_matrix()`` returns a sorted, timestamp-free,
randomness-free dict; the same source produces byte-identical output. This is
required by the CI ``extract-docs-drift`` gate, which re-runs the generator and
fails on any uncommitted change.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
OUTPUT = ROOT / "docs" / "_generated" / "adapter-certification-matrix.json"


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def main() -> int:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    try:
        from shared.certification.registry import build_capability_matrix
    except Exception as exc:  # pragma: no cover — surfaces a real wiring break
        print(
            f"error: could not import certification registry: {exc}",
            file=sys.stderr,
        )
        return 1

    matrix = build_capability_matrix()
    payload = {
        "version": read_version(),
        "generated_from": (
            "Backend Architecture/aether-backend/shared/certification/registry.py"
        ),
        **matrix,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
    total = summary.get("total", "?")
    by_state = summary.get("by_state", {})
    print(
        f"extract_adapter_certification: wrote {OUTPUT.relative_to(ROOT)} "
        f"({total} first-release providers; by_state={by_state})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
