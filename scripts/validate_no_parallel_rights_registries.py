#!/usr/bin/env python3
"""Rights Authority no-parallel-registries architecture validator (Phase 0).

Enforces blueprint §13 / ADR-011 D4: rights data-authority state stays in its
owning canonical authorities; a duplicate rights ledger is forbidden. Scans the
repo for files whose exact basename is one of the prohibited duplicate
data-authority ledger names:

  irrl-registry.json
  ownership-registry.json
  learning-rights-registry.json
  retention-rights-registry.json
  generalization-rights-registry.json

Exact-basename matching only — ``projector-ownership-registry.json`` and other
differently-named registries are NOT matches. A file with one of those names is
permitted ONLY if it is a true canonical vocabulary:

  (a) its repo-relative path is listed under ``registeredCanonicalVocabularies``
      in packages/shared/contracts/rights-vocabulary.json, or
  (b) its top-level JSON carries ``schemaVersion`` + ``contractVersion`` and its
      repo-relative path is declared in the ``rights_irrl`` spine row's
      ``canonicalContractRefs`` in packages/shared/contracts/spine-registry.json.

Any other hit is a violation naming the path and the doctrine it breaks.
Directories excluded: .git, node_modules, dist, docs/_generated (generated
output), plus virtualenvs.

Usage:
  python scripts/validate_no_parallel_rights_registries.py [--check]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
VOCAB_PATH = ROOT / "packages" / "shared" / "contracts" / "rights-vocabulary.json"
SPINE_REGISTRY_PATH = ROOT / "packages" / "shared" / "contracts" / "spine-registry.json"
RIGHTS_SPINE_ID = "rights_irrl"

# Prohibited duplicate data-authority ledger names (blueprint §13).
FORBIDDEN_BASENAMES = frozenset(
    {
        "irrl-registry.json",
        "ownership-registry.json",
        "learning-rights-registry.json",
        "retention-rights-registry.json",
        "generalization-rights-registry.json",
    }
)

# Directory names that are never scanned.
EXCLUDED_DIRS = frozenset({".git", "node_modules", "dist", "_generated", ".venv"})

VIOLATIONS: list[str] = []
ERRORS: list[str] = []


def err(msg: str) -> None:
    ERRORS.append(msg)


def _load_json(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _is_canonical_vocabulary_doc(doc: Optional[dict]) -> bool:
    return bool(
        doc
        and isinstance(doc.get("schemaVersion"), str)
        and doc.get("schemaVersion")
        and isinstance(doc.get("contractVersion"), str)
        and doc.get("contractVersion")
    )


def _rights_irrl_contract_registries(spine_registry: dict) -> set[str]:
    """repo-relative canonicalContractRefs registry paths on the rights_irrl row."""
    for spine in spine_registry.get("spines", []):
        if isinstance(spine, dict) and spine.get("id") == RIGHTS_SPINE_ID:
            refs = spine.get("canonicalContractRefs", [])
            return {
                ref.get("registry")
                for ref in refs
                if isinstance(ref, dict) and isinstance(ref.get("registry"), str)
            }
    return set()


def validate_registered_canonical_vocabularies(vocab: dict) -> None:
    """The allowlist must only contain real canonical vocabulary JSON files."""
    registered = vocab.get("registeredCanonicalVocabularies", [])
    if not isinstance(registered, list):
        err("no-parallel: registeredCanonicalVocabularies must be a list")
        return
    for entry in registered:
        if not isinstance(entry, str) or not entry:
            err("no-parallel: registeredCanonicalVocabularies entries must be path strings")
            continue
        path = ROOT / entry
        if not path.is_file():
            err(
                f"no-parallel: registeredCanonicalVocabularies entry {entry!r} is not an "
                "existing file"
            )
            continue
        if not _is_canonical_vocabulary_doc(_load_json(path)):
            err(
                f"no-parallel: registeredCanonicalVocabularies entry {entry!r} is not a true "
                "canonical vocabulary (missing schemaVersion/contractVersion)"
            )


def scan(registered: set[str], contract_registries: set[str]) -> tuple[int, int]:
    """Return (files_scanned, violations_found) walking ROOT."""
    found = 0
    violations = 0
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(
            d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")
        )
        for filename in filenames:
            if filename not in FORBIDDEN_BASENAMES:
                continue
            found += 1
            abs_path = Path(dirpath) / filename
            rel = abs_path.relative_to(ROOT).as_posix()
            if rel in registered:
                continue
            if rel in contract_registries and _is_canonical_vocabulary_doc(_load_json(abs_path)):
                continue
            violations += 1
            VIOLATIONS.append(
                f"{rel}: forbidden duplicate data-authority ledger name {filename!r} — a "
                "parallel rights registry is forbidden (ADR-011 D4; "
                "RIGHTS_AUTHORITY_BLUEPRINT.md §13); rights state must stay in its owning "
                "canonical authorities. Register it as a true canonical vocabulary under "
                "registeredCanonicalVocabularies in rights-vocabulary.json or under the "
                "rights_irrl spine row's canonicalContractRefs, or rename it."
            )
    return found, violations


def _parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI gate (default mode): exit 0 on no violations, 1 otherwise",
    )
    parser.add_argument(
        "--vocab",
        metavar="PATH",
        default=str(VOCAB_PATH),
        help="canonical vocabulary JSON (default packages/shared/contracts/rights-vocabulary.json)",
    )
    parser.add_argument(
        "--registry",
        metavar="PATH",
        default=str(SPINE_REGISTRY_PATH),
        help="spine-registry JSON (default packages/shared/contracts/spine-registry.json)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    del VIOLATIONS[:]
    del ERRORS[:]
    args = _parse_args(argv)
    vocab_path = Path(args.vocab)
    spine_path = Path(args.registry)

    vocab = _load_json(vocab_path)
    if vocab is None:
        err(f"no-parallel: missing/invalid vocabulary JSON {vocab_path.relative_to(ROOT)}")
    else:
        validate_registered_canonical_vocabularies(vocab)

    spine_registry = _load_json(spine_path)
    if spine_registry is None:
        err(f"no-parallel: missing/invalid spine registry JSON {spine_path.relative_to(ROOT)}")

    registered = set()
    if isinstance(vocab, dict):
        raw = vocab.get("registeredCanonicalVocabularies", [])
        if isinstance(raw, list):
            registered = {entry for entry in raw if isinstance(entry, str)}
    contract_registries = (
        _rights_irrl_contract_registries(spine_registry) if spine_registry else set()
    )

    if ERRORS:
        print("no-parallel-rights-registries validation FAILED:")
        for message in ERRORS:
            print(f"  - {message}")
        return 1

    found, _violations = scan(registered, contract_registries)
    for violation in VIOLATIONS:
        print(f"  - {violation}")
    if VIOLATIONS:
        print(
            f"no-parallel-rights-registries: {len(VIOLATIONS)} violation(s) — duplicate "
            "data-authority ledgers are forbidden (ADR-011 D4 / blueprint §13)"
        )
        return 1

    print(
        f"no-parallel-rights-registries: OK — scanned {found} matching-name file(s); no "
        "duplicate data-authority ledger present"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(2)
