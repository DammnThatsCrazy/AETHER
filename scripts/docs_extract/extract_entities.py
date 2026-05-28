#!/usr/bin/env python3
"""Generate ``docs/_generated/entities.json`` from ``packages/shared/entities.ts``.

The entity model is the canonical contract that maps SDK ``EntityRef``s
to backend graph vertex types. This generator parses the ``EntityKind``
union and preserves the section comments that group entities into planes
(Core, Access, Commerce, Web3, Agent, Economic).

Schema::

    {
      "version": "8.8.0",
      "generated_from": "packages/shared/entities.ts",
      "planes": [
        {
          "name": "Core (always present)",
          "kinds": ["tenant", "org", "user", ...]
        },
        ...
      ],
      "all_kinds": [...]
    }

Determinism: planes and kinds appear in source order. Same input produces
byte-identical output.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENTITIES_TS = ROOT / "packages" / "shared" / "entities.ts"
OUTPUT = ROOT / "docs" / "_generated" / "entities.json"

MEMBER_RE = re.compile(r"\|\s*'([^']+)'")
SECTION_RE = re.compile(r"^\s*//\s*(.+)")


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def parse_planes(text: str) -> list[dict]:
    # Locate the EntityKind type alias with a simple non-backtracking search.
    start = text.find("export type EntityKind =")
    if start == -1:
        raise ValueError("could not locate EntityKind union in entities.ts")
    # Find the closing semicolon that ends the union.
    end = text.find(";", start)
    if end == -1:
        raise ValueError("could not find closing ';' for EntityKind union")
    union_block = text[start:end + 1]

    planes: list[dict] = []
    current: dict = {"name": "Uncategorized", "kinds": []}
    in_union = False

    for line in union_block.splitlines():
        stripped = line.strip()
        if not in_union:
            in_union = True
            continue  # skip the "export type EntityKind =" line itself

        # Comment-only line (no pipe) → start a new section plane.
        if stripped.startswith("//") and "|" not in stripped:
            # Strip decorative chars: ─, ─, spaces, dashes, leading slashes
            name = re.sub(r"^[/\s─\-─]+|[─\-─\s]+$", "", stripped).strip()
            if name:
                if current["kinds"]:
                    planes.append(current)
                current = {"name": name, "kinds": []}
            continue

        # Kind line: | 'foo'  // optional inline comment
        member = MEMBER_RE.search(stripped)
        if member:
            current["kinds"].append(member.group(1))

    if current["kinds"]:
        planes.append(current)

    if not planes:
        raise ValueError("EntityKind union parsed but found no kinds")

    return planes


def build_payload(text: str) -> dict:
    planes = parse_planes(text)
    all_kinds = [k for p in planes for k in p["kinds"]]

    duplicates = {k for k in all_kinds if all_kinds.count(k) > 1}
    if duplicates:
        raise ValueError(f"EntityKind has duplicate members: {sorted(duplicates)}")

    return {
        "version": read_version(),
        "generated_from": "packages/shared/entities.ts",
        "planes": planes,
        "all_kinds": all_kinds,
    }


def main() -> int:
    if not ENTITIES_TS.exists():
        print(f"error: {ENTITIES_TS} not found", file=sys.stderr)
        return 1

    text = ENTITIES_TS.read_text(encoding="utf-8")
    try:
        payload = build_payload(text)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"extract_entities: wrote {OUTPUT.relative_to(ROOT)} "
        f"({len(payload['all_kinds'])} kinds across {len(payload['planes'])} planes)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
