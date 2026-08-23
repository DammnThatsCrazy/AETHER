"""Generated-artifact parity gate (program §25/§28).

The docs generators under ``scripts/docs_extract/`` emit the JSON artifacts in
``docs/_generated/`` from source. Those artifacts are NEVER hand-edited. This
test re-derives the expected payload IN MEMORY (calling the same pure
``build_payload``/``build_capability_matrix`` code the generators use) and
compares it to the committed artifact — it never writes a file, so it can run
in CI without mutating the tree.

Covered artifacts (all sourced from backend Python modules this repo owns):
  - docs/_generated/adapter-certification-matrix.json  <- shared/certification/registry.py
  - docs/_generated/plans.json                          <- shared/plans/catalog.py
  - docs/_generated/providers.json                      <- shared/providers/categories.py
  - docs/_generated/topics.json                         <- shared/events/events.py

TypeScript-sourced artifacts (capabilities/consent/entities/events from
``packages/shared/*.ts``) are out of scope for this offline Python gate and are
covered by the repo-doctor extract-docs-drift CI gate.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATED_DIR = REPO_ROOT / "docs" / "_generated"
BACKEND_ROOT = (
    REPO_ROOT / "Backend Architecture" / "aether-backend"
)
PYPROJECT = REPO_ROOT / "pyproject.toml"

for _p in (str(BACKEND_ROOT), str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("AETHER_ENV", "local")


def _load_script(module_name: str, rel_path: str) -> Any:
    """Import a scripts/docs_extract generator WITHOUT executing its main()."""
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def _committed(path: str) -> dict:
    return json.loads((GENERATED_DIR / path).read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════
# plans / providers / topics — pure build_payload parity
# ══════════════════════════════════════════════════════════════════════════


def _plans_payload() -> dict:
    extract = _load_script("extract_plans", "scripts/docs_extract/extract_plans.py")
    src = (BACKEND_ROOT / "shared" / "plans" / "catalog.py").read_text(encoding="utf-8")
    return extract.build_payload(src)


def _providers_payload() -> dict:
    extract = _load_script("extract_providers", "scripts/docs_extract/extract_providers.py")
    src = (BACKEND_ROOT / "shared" / "providers" / "categories.py").read_text(encoding="utf-8")
    return extract.build_payload(src)


def _topics_payload() -> dict:
    extract = _load_script("extract_topics", "scripts/docs_extract/extract_topics.py")
    src = (BACKEND_ROOT / "shared" / "events" / "events.py").read_text(encoding="utf-8")
    return extract.build_payload(src)


def test_plans_json_matches_generator() -> None:
    assert _plans_payload() == _committed("plans.json")


def test_providers_json_matches_generator() -> None:
    assert _providers_payload() == _committed("providers.json")


def test_topics_json_matches_generator() -> None:
    assert _topics_payload() == _committed("topics.json")


# ══════════════════════════════════════════════════════════════════════════
# adapter-certification-matrix — rebuilt from the certification registry
# ══════════════════════════════════════════════════════════════════════════


def _certification_matrix_payload() -> dict:
    """Reconstruct exactly what scripts/docs_extract/extract_adapter_certification.py
    writes: ``{version, generated_from, **build_capability_matrix()}``."""
    from shared.certification.registry import build_capability_matrix

    return {
        "version": _pyproject_version(),
        "generated_from": (
            "Backend Architecture/aether-backend/shared/certification/registry.py"
        ),
        **build_capability_matrix(),
    }


def test_adapter_certification_matrix_matches_registry() -> None:
    """The committed matrix must equal the source registry's capability matrix.

    Canary for the provider sweep: adding/removing a first-release provider in
    the registry without regenerating this doc breaks parity and fails here.
    """
    expected = _certification_matrix_payload()
    committed = _committed("adapter-certification-matrix.json")
    assert expected == committed, _matrix_diff_report(expected, committed)


def test_certification_matrix_provider_coverage() -> None:
    """Every provider in the source registry must appear in the generated doc
    (and vice versa) — a focused view of the same parity requirement."""
    expected = _certification_matrix_payload()
    committed = _committed("adapter-certification-matrix.json")

    expected_keys = set(expected["providers"])
    committed_keys = set(committed.get("providers", {}))
    only_expected = sorted(expected_keys - committed_keys)
    only_committed = sorted(committed_keys - expected_keys)

    assert not only_expected, (
        "generated adapter-certification-matrix.json is missing provider(s) "
        f"that exist in the registry: {only_expected}. Regenerate the doc."
    )
    assert not only_committed, (
        "generated adapter-certification-matrix.json lists provider(s) not in "
        f"the registry: {only_committed}. Regenerate the doc."
    )


def _matrix_diff_report(expected: dict, committed: dict) -> str:
    lines = [
        "adapter-certification-matrix.json is out of parity with "
        "shared/certification/registry.py (do NOT hand-edit the doc; "
        "regenerate via the docs_extract generator)."
    ]
    e_sum = expected.get("summary", {})
    c_sum = committed.get("summary", {})
    if e_sum != c_sum:
        lines.append(f"  summary source   : {e_sum}")
        lines.append(f"  summary committed: {c_sum}")
    exp_keys = set(expected.get("providers", {}))
    com_keys = set(committed.get("providers", {}))
    if exp_keys - com_keys:
        lines.append("  in registry but not in doc: " + ", ".join(sorted(exp_keys - com_keys)))
    if com_keys - exp_keys:
        lines.append("  in doc but not in registry: " + ", ".join(sorted(com_keys - exp_keys)))
    if expected.get("version") != committed.get("version"):
        lines.append(
            f"  version mismatch: source={expected.get('version')!r} "
            f"committed={committed.get('version')!r}"
        )
    return "\n".join(lines)
