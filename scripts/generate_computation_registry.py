#!/usr/bin/env python3
"""Generate the computation-substrate registry twin.

Writes ``shared/computation/generated_registry.py`` from the hand-authored
``shared/computation/registry.py``. The generated file is a pure data snapshot
(stdlib only) so it can be imported without pulling the substrate's runtime
dependencies. A parity test / the substrate validator asserts the in-code
registry still serializes to exactly this snapshot; regenerate with::

    python scripts/generate_computation_registry.py

Do not hand-edit the generated file — change ``registry.py`` and regenerate.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
OUT = BACKEND / "shared" / "computation" / "generated_registry.py"


def _snapshot() -> list[dict]:
    sys.path.insert(0, str(BACKEND))
    from shared.computation.registry import list_definitions  # noqa: E402

    defs = [d.model_dump(mode="json") for d in list_definitions()]
    defs.sort(key=lambda d: (d["definition_id"], d["definition_version"]))
    return defs


def _digest(defs: list[dict]) -> str:
    payload = json.dumps(defs, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render(defs: list[dict], digest: str) -> str:
    # Embed as a JSON string parsed at import so the file stays pure-stdlib and
    # valid Python (JSON null/true/false are not Python literals).
    body = json.dumps(defs, indent=2, sort_keys=True)
    return (
        '"""GENERATED — do not edit. Source: shared/computation/registry.py.\n\n'
        "Regenerate with ``python scripts/generate_computation_registry.py``.\n"
        "Parity is asserted by tests/computation/test_registry_parity.py and\n"
        "scripts/validate_computation_substrate.py.\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        "import json\n\n"
        f'REGISTRY_DIGEST = "{digest}"\n\n'
        '_DEFINITIONS_JSON = """\n'
        f"{body}\n"
        '"""\n\n'
        "GENERATED_DEFINITIONS = json.loads(_DEFINITIONS_JSON)\n\n\n"
        "def definition_ids() -> list[str]:\n"
        '    return [d["definition_id"] for d in GENERATED_DEFINITIONS]\n\n\n'
        '__all__ = ["REGISTRY_DIGEST", "GENERATED_DEFINITIONS", "definition_ids"]\n'
    )


def main() -> int:
    defs = _snapshot()
    digest = _digest(defs)
    OUT.write_text(render(defs, digest), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(defs)} definitions, digest {digest[:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
