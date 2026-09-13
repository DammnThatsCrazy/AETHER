#!/usr/bin/env python3
"""Validate the schemas and registries that form the adaptive CI contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _schema(path: Path, draft: type[jsonschema.Validator]) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    draft.check_schema(raw)


def main() -> int:
    errors: list[str] = []
    delivery_schemas = sorted((ROOT / "contracts/delivery").glob("*.schema.json"))
    for path in delivery_schemas:
        try:
            _schema(path, jsonschema.Draft202012Validator)
        except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")

    try:
        suite_schema = json.loads((ROOT / "config/test_suites.schema.json").read_text(encoding="utf-8"))
        suite_registry = yaml.safe_load((ROOT / "config/test_suites.yaml").read_text(encoding="utf-8"))
        jsonschema.Draft7Validator(suite_schema).validate(suite_registry)
    except (OSError, json.JSONDecodeError, yaml.YAMLError, jsonschema.SchemaError, jsonschema.ValidationError) as exc:
        errors.append(f"test-suite registry/schema: {exc}")

    status = "PASS" if not errors else "FAILED"
    print(json.dumps({
        "schema_version": 1,
        "status": status,
        "delivery_schema_count": len(delivery_schemas),
        "test_suite_schema": "config/test_suites.schema.json",
        "errors": errors,
    }, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
