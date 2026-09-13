#!/usr/bin/env python3
"""Verify the exact candidate and build-selection closure without rerunning tests."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.artifact_builder import verify_candidate  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--repository-build", type=Path)
    parser.add_argument("--backend-image", type=Path)
    parser.add_argument("--build-selection", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.monotonic()
    errors: list[str] = []
    candidate = None
    try:
        selection = json.loads(args.build_selection.read_text(encoding="utf-8"))
        expected_image = bool(selection.get("backend_image"))
        if expected_image != bool(args.backend_image):
            raise ValueError("backend image presence disagrees with Impact Graph build selection")
        node_required = bool(selection.get("node_required"))
        if node_required != bool(args.repository_build):
            raise ValueError("repository build presence disagrees with Impact Graph build selection")
        components = []
        if args.repository_build:
            components.append(f"repository-build={args.repository_build}")
        if args.backend_image:
            components.append(f"backend-image={args.backend_image}")
        if not components:
            raise ValueError("candidate verification requires at least one selected build artifact")
        candidate = verify_candidate(args.candidate, components, ["package-lock.json", "pyproject.toml"], args.expected_commit)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    status = "PASS" if not errors else "FAILED"
    payload = {
        "schema_version": 1,
        "stage": "candidate-verification",
        "status": status,
        "candidate_path": str(args.candidate),
        "commit_sha": args.expected_commit,
        "artifact_digest": candidate.get("artifact_digest", "") if candidate else "",
        "candidate_verification_seconds": time.monotonic() - started,
        "errors": errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
