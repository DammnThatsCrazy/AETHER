#!/usr/bin/env python3
"""Generate ``docs/_generated/env.json`` from ``.env.example``.

The reference env-vars page in the docs site is the single most-requested
piece by self-hosters. Keeping it in sync with ``.env.example`` by hand
guarantees drift. This generator parses the example file's lightweight
``=== Section ===`` / ``VAR=value`` syntax and emits a structured JSON
catalog.

Schema of the output::

    {
      "version": "8.9.0",
      "generated_from": ".env.example",
      "categories": [
        {
          "name": "General",
          "vars": [
            {
              "name": "AETHER_ENV",
              "default": "local",
              "description": "local | dev | staging | production",
              "required_in_production": false
            },
            ...
          ]
        },
        ...
      ]
    }

Determinism: output is sorted by source order (the same order the file
declares the vars), so a re-run on unchanged input produces byte-identical
JSON. The drift detector relies on this.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENV_EXAMPLE = ROOT / ".env.example"
OUTPUT = ROOT / "docs" / "_generated" / "env.json"

SECTION_RE = re.compile(r"^#\s*===\s*(.+?)\s*===\s*$")
# Match ``NAME=value`` optionally followed by ``# trailing comment``.
# Allow value to be empty. Allow names with letters, digits, underscore.
VAR_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*?)(?:\s+#\s*(.*))?$")
REQUIRED_MARKER = "[REQUIRED IN PRODUCTION]"


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def parse_env_example(text: str) -> list[dict]:
    """Walk the file and group variables under section headings.

    Returns a list of categories with embedded var dicts. The first
    section before any ``=== ... ===`` line is named ``"Header"``.
    """
    categories: list[dict] = []
    current = {"name": "Header", "vars": []}

    for line in text.splitlines():
        stripped = line.rstrip()
        if not stripped:
            continue

        section = SECTION_RE.match(stripped)
        if section:
            if current["vars"]:
                categories.append(current)
            current = {"name": section.group(1), "vars": []}
            continue

        if stripped.startswith("#"):
            continue  # comment block — discarded for now

        var = VAR_RE.match(stripped)
        if not var:
            continue  # malformed line — skip without failing

        name, default, comment = var.group(1), var.group(2), var.group(3) or ""
        required = REQUIRED_MARKER in comment
        description = comment.replace(REQUIRED_MARKER, "").strip()
        current["vars"].append({
            "name": name,
            "default": default,
            "description": description,
            "required_in_production": required,
        })

    if current["vars"]:
        categories.append(current)
    return categories


def main() -> int:
    if not ENV_EXAMPLE.exists():
        print(f"error: {ENV_EXAMPLE} not found", file=sys.stderr)
        return 1

    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    categories = parse_env_example(text)

    if not categories:
        print("error: no categories parsed — is the format valid?", file=sys.stderr)
        return 1

    payload = {
        "version": read_version(),
        "generated_from": ".env.example",
        "categories": categories,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    total_vars = sum(len(c["vars"]) for c in categories)
    required_vars = sum(
        sum(1 for v in c["vars"] if v["required_in_production"])
        for c in categories
    )
    print(
        f"extract_env: wrote {OUTPUT.relative_to(ROOT)} "
        f"({len(categories)} categories, {total_vars} vars, "
        f"{required_vars} required in production)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
