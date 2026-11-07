#!/usr/bin/env python3
"""Validate financial capability records across the registries that bind them.

Checks the generated capability matrix against the canonical release manifest,
route registry, service classification, deployment profiles, data-rights
vocabulary, canonical event vocabularies, and owner paths.  Financial domains
are not production-enabled today, so any production claim fails closed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = ROOT / "services" / "api"


def _load(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def main() -> int:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from connectors.integrations.data_rights.models import SourceUseAuthority
    from shared.certification.capability_records import (
        build_financial_capability_matrix,
        validate_financial_capability_matrix,
    )
    from shared.certification.registry import import_errors, iter_financial_descriptors

    release_manifest = _load(ROOT / "config" / "founding_tenant_release.yaml")
    matrix = build_financial_capability_matrix(
        iter_financial_descriptors(), release_manifest=release_manifest
    )
    errors = validate_financial_capability_matrix(
        matrix,
        service_classification=_load(ROOT / "config" / "service_classification.yaml"),
        route_registry=_load(ROOT / "config" / "route_registry.yaml"),
        release_manifest=release_manifest,
        deployment_profiles=_load(ROOT / "config" / "deployment_profiles.yaml"),
        data_rights_fields=SourceUseAuthority.model_fields,
        root=ROOT,
    )
    errors.extend(f"adapter import error: {key}: {value}" for key, value in import_errors().items())

    if errors:
        print("financial capability registry validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    summary = matrix["summary"]
    print(
        "financial capability registry OK: "
        f"{summary['total']} records across {summary['domains']} domains; "
        f"production_eligible={summary['production_eligible']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
