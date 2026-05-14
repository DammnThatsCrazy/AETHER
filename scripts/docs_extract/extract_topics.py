#!/usr/bin/env python3
"""Generate ``docs/_generated/topics.json`` from the Kafka Topic enum.

The Kafka topic registry is the integration contract every event-bus
consumer pins against. Hand-maintaining it next to the canonical Python
enum guarantees drift — services would publish on a name the docs say
doesn't exist.

Source::

    Backend Architecture/aether-backend/shared/events/events.py
    -> class Topic(str, Enum)

Parses the class body via Python ``ast`` so it doesn't need to import
the backend module (which transitively requires aiokafka, asyncpg,
etc.). Section comments (``# Identity``, ``# Commerce``, ...) are
preserved and used to group topics into named sections, matching the
plan's docs-site topic page layout.

Schema::

    {
      "version": "8.8.0",
      "generated_from": "Backend Architecture/aether-backend/shared/events/events.py",
      "sections": [
        {
          "name": "Ingestion",
          "topics": [
            {"member": "SDK_EVENTS_RAW", "value": "aether.sdk.events.raw"},
            ...
          ]
        },
        ...
      ],
      "all_topics": [...]
    }

Determinism: sections + topics appear in source order. Same input
produces byte-identical output.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tokenize
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EVENTS_PY = (
    ROOT
    / "Backend Architecture"
    / "aether-backend"
    / "shared"
    / "events"
    / "events.py"
)
OUTPUT = ROOT / "docs" / "_generated" / "topics.json"


class ParseError(Exception):
    """Raised when events.py doesn't match the expected shape."""


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def _find_class_def(text: str, name: str) -> ast.ClassDef:
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise ParseError(f"class {name} not found in events.py")


def _class_source(text: str, cls: ast.ClassDef) -> str:
    """Return just the source lines of one class body."""
    lines = text.splitlines(keepends=True)
    # ast nodes are 1-indexed; end_lineno is inclusive.
    start = cls.lineno - 1
    end = cls.end_lineno or len(lines)
    return "".join(lines[start:end])


def parse_topic_class(text: str) -> list[dict]:
    """Walk the Topic class body in source order; emit sections.

    The tokeniser is used to associate ``# section`` comments with the
    members that follow them. ast alone strips comments. We:
      1. Locate `class Topic(...)` via ast for its line range.
      2. Re-tokenise that slice to find comment positions.
      3. Walk the class body statements in source order and emit a new
         section every time a leading comment appears.
    """
    cls = _find_class_def(text, "Topic")
    body_src = _class_source(text, cls)

    # Map line numbers (within body_src) -> comment text for `# Foo` lines
    # that start a new section.
    comments_by_line: dict[int, str] = {}
    try:
        tokens = list(tokenize.generate_tokens(StringIO(body_src).readline))
    except tokenize.TokenizeError as exc:
        raise ParseError(f"could not tokenise Topic class body: {exc}") from exc
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            ln = tok.start[0]
            text_stripped = tok.string.lstrip("#").strip()
            # Only the first comment on a line counts as a section header.
            comments_by_line.setdefault(ln, text_stripped)

    # ast positions are absolute to the file; class body member statements
    # need to be shifted into body_src coordinates.
    line_offset = cls.lineno - 1
    sections: list[dict] = []
    current = {"name": "Unsectioned", "topics": []}

    # Walk class body statements in declaration order.
    body_lines = body_src.splitlines()
    for stmt in cls.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            continue
        if not isinstance(stmt.value, ast.Constant) or not isinstance(stmt.value.value, str):
            continue

        member = stmt.targets[0].id
        value = stmt.value.value

        # Walk back collecting the *block* of pure-comment lines that
        # immediately precedes this assignment. Blanks are allowed to
        # separate but a non-comment code line terminates the block.
        # The topmost comment in the block becomes the section header —
        # subordinate notes like ``# All new topics; no existing topic
        # is renamed`` are skipped over to find the real section line
        # above them.
        stmt_line = stmt.lineno - line_offset
        comment_block_probes: list[int] = []
        for probe in range(stmt_line - 1, max(0, stmt_line - 12), -1):
            if probe - 1 >= len(body_lines):
                continue
            line_text = body_lines[probe - 1]
            stripped = line_text.strip()
            if not stripped:
                # Blank line — comment block continues across it only
                # if comments resume.
                continue
            if stripped.startswith("#") and probe in comments_by_line:
                comment_block_probes.append(probe)
                continue
            # Non-comment code line — comment block ends.
            break

        if comment_block_probes:
            # Probes were collected walking upward from stmt_line-1; the
            # smallest probe number is the highest (topmost) source line
            # in the comment block — that's the section header.
            topmost = min(comment_block_probes)
            new_section_name = comments_by_line[topmost]
            if new_section_name != current["name"]:
                if current["topics"]:
                    sections.append(current)
                current = {"name": new_section_name, "topics": []}

        current["topics"].append({"member": member, "value": value})

    if current["topics"]:
        sections.append(current)
    return sections


def build_payload(text: str) -> dict:
    sections = parse_topic_class(text)
    all_topics = [t for s in sections for t in s["topics"]]

    # Sanity: values must be unique.
    values = [t["value"] for t in all_topics]
    duplicates = {v for v in values if values.count(v) > 1}
    if duplicates:
        raise ParseError(f"Topic enum has duplicate values: {sorted(duplicates)}")

    # Sanity: at least one topic captured.
    if not all_topics:
        raise ParseError("Topic enum body parsed empty — source may have moved")

    return {
        "version": read_version(),
        "generated_from": "Backend Architecture/aether-backend/shared/events/events.py",
        "sections": sections,
        "all_topics": all_topics,
    }


def main() -> int:
    if not EVENTS_PY.exists():
        print(f"error: {EVENTS_PY} not found", file=sys.stderr)
        return 1

    text = EVENTS_PY.read_text(encoding="utf-8")
    try:
        payload = build_payload(text)
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"extract_topics: wrote {OUTPUT.relative_to(ROOT)} "
        f"({len(payload['all_topics'])} topics across "
        f"{len(payload['sections'])} sections)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
