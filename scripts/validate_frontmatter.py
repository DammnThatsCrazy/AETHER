#!/usr/bin/env python3
"""Validate YAML frontmatter on Aether documentation pages.

Reads scripts/docs_schema.json and walks tracked .md / .mdx files under
docs/ (excluding archive/ and _generated/). For each file:

  - If the file has YAML frontmatter (delimited by lines of exactly ---),
    parse and validate it against the schema.
  - If the file does not have frontmatter, fail (back-fill is complete as
    of slice 3 — all authored docs are required to declare visibility,
    audience, etc.).

Exit codes:
  0  every checked file has valid frontmatter
  1  one or more files have invalid or missing frontmatter
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "scripts" / "docs_schema.json"
DOCS_ROOT = ROOT / "docs"

# Subtrees skipped entirely.
SKIP_DIRS = {
    DOCS_ROOT / "archive",
    DOCS_ROOT / "_generated",
    DOCS_ROOT / "_templates",
    DOCS_ROOT / "diagrams",
    DOCS_ROOT / "examples",
    DOCS_ROOT / "source-of-truth",
}

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class ValidationError(Exception):
    """Schema validation failure with a file-attributable message."""


def load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open() as fh:
        return json.load(fh)


def tracked_docs() -> list[Path]:
    """Return tracked .md / .mdx files under docs/, sorted, filtered."""
    result = subprocess.run(
        ["git", "ls-files", "docs/**.md", "docs/**.mdx", "docs/*.md", "docs/*.mdx"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = ROOT / line
        if any(skip in path.parents for skip in SKIP_DIRS):
            continue
        paths.append(path)
    return sorted(paths)


def extract_frontmatter(text: str) -> dict[str, Any] | None:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValidationError(f"YAML parse error: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValidationError("frontmatter must be a mapping")
    return data


def _check_type(value: Any, expected: str, path: str) -> None:
    type_map = {
        "string": str,
        "integer": int,
        "array": list,
        "object": dict,
        "boolean": bool,
    }
    py_type = type_map.get(expected)
    if py_type is None:
        return
    # bool is a subclass of int in Python — reject it where integer is expected.
    if expected == "integer" and isinstance(value, bool):
        raise ValidationError(f"{path}: expected integer, got boolean")
    if not isinstance(value, py_type):
        raise ValidationError(
            f"{path}: expected {expected}, got {type(value).__name__}"
        )


def _check_enum(value: Any, enum: list[Any], path: str) -> None:
    if value not in enum:
        raise ValidationError(
            f"{path}: value {value!r} not one of {enum}"
        )


def _check_pattern(value: str, pattern: str, path: str) -> None:
    if not re.fullmatch(pattern, value):
        raise ValidationError(f"{path}: value {value!r} does not match /{pattern}/")


def _validate_against(value: Any, prop_schema: dict[str, Any], path: str) -> None:
    expected_type = prop_schema.get("type")
    if expected_type:
        _check_type(value, expected_type, path)
    if "enum" in prop_schema:
        _check_enum(value, prop_schema["enum"], path)
    if "pattern" in prop_schema and isinstance(value, str):
        _check_pattern(value, prop_schema["pattern"], path)
    if expected_type == "string":
        min_len = prop_schema.get("minLength")
        if min_len is not None and len(value) < min_len:
            raise ValidationError(f"{path}: string shorter than minLength {min_len}")
    if expected_type == "integer":
        minimum = prop_schema.get("minimum")
        maximum = prop_schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ValidationError(f"{path}: {value} < minimum {minimum}")
        if maximum is not None and value > maximum:
            raise ValidationError(f"{path}: {value} > maximum {maximum}")
    if expected_type == "array":
        if prop_schema.get("uniqueItems") and len(set(map(repr, value))) != len(value):
            raise ValidationError(f"{path}: array has duplicate items")
        min_items = prop_schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            raise ValidationError(f"{path}: array shorter than minItems {min_items}")
        item_schema = prop_schema.get("items")
        if item_schema:
            for i, item in enumerate(value):
                _validate_against(item, item_schema, f"{path}[{i}]")


def validate_frontmatter(data: dict[str, Any], schema: dict[str, Any]) -> None:
    props = schema.get("properties", {})
    required = schema.get("required", [])
    additional = schema.get("additionalProperties", True)

    for key in required:
        if key not in data:
            raise ValidationError(f"missing required key '{key}'")

    for key, value in data.items():
        if key not in props:
            if additional is False:
                raise ValidationError(f"unknown key '{key}' (additionalProperties=false)")
            continue
        _validate_against(value, props[key], key)


def main() -> int:
    schema = load_schema()
    docs = tracked_docs()

    errors: list[str] = []
    validated = 0

    for path in docs:
        rel = path.relative_to(ROOT)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{rel}: read error: {exc}")
            continue

        try:
            data = extract_frontmatter(text)
        except ValidationError as exc:
            errors.append(f"{rel}: {exc}")
            continue

        if data is None:
            errors.append(
                f"{rel}: missing frontmatter. "
                f"Use docs/_templates/page.template.mdx as a starter."
            )
            continue

        try:
            validate_frontmatter(data, schema)
        except ValidationError as exc:
            errors.append(f"{rel}: {exc}")
            continue

        validated += 1

    print(f"Frontmatter validator: {len(docs)} files scanned, {validated} validated, "
          f"{len(errors)} errors.")

    if errors:
        print()
        print("ERRORS:")
        for e in errors:
            print(f"  - {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
