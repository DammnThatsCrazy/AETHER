#!/usr/bin/env python3
"""Rights Authority canonical-vocabulary tri-surface parity validator (Phase 0).

Fail-closed cross-check of the three hand-written surfaces that must speak the
exact same canonical rights vocabulary (RIGHTS_AUTHORITY_BLUEPRINT §3–§9,
IRRL_NAMING_OVERLAY.md):

  1. packages/shared/contracts/rights-vocabulary.json  (the canonical contract;
     this file owns the enumerated snake_case value sets)
  2. Backend .../services/integrations/data_rights/models.py   (Python enums)
  3. packages/shared/data-rights.ts                            (TS ``as const``
     arrays)

None of these files is generated; this validator is what keeps them from
drifting. It fails (exit 1) with a precise diff on ANY disagreement about
membership, an enumeration value that is not lower_snake, a missing twin enum /
array, a missing or non-canonical twin file, a migration mapping that broadens,
a profile-defaults table that disagrees with the profile vocabulary, or a
bindings table that leaves a vocabulary key unbound.

Every vocabulary key declared in the JSON is either bound to a Python enum class
(``bindings.<key>.pythonEnum``) and a TS array (``bindings.<key>.tsArray``) with
EXACT member-set equality to this JSON, or allowlisted
(``bindings.<key>.allowlisted == true``) because it is a record/table or a
vocabulary carried by a later runtime surface (e.g. the Generalization Gateway).
A vocabulary key that is neither bound nor allowlisted is a violation.

The current checkout is expected to fail until the parallel python-enum and TS
twin streams land the enums/arrays declared by ``bindings`` (this validator is
the gate that forces the three surfaces to converge).

Usage:
  python scripts/validate_rights_vocabulary.py [--check]
  python scripts/validate_rights_vocabulary.py \
      [--vocab packages/shared/contracts/rights-vocabulary.json] \
      [--models Backend\\ Architecture/aether-backend/services/integrations/data_rights/models.py] \
      [--ts packages/shared/data-rights.ts]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
VOCAB_PATH = ROOT / "packages" / "shared" / "contracts" / "rights-vocabulary.json"
PY_MODELS_PATH = (
    ROOT
    / "Backend Architecture"
    / "aether-backend"
    / "services"
    / "integrations"
    / "data_rights"
    / "models.py"
)
TS_TWIN_PATH = ROOT / "packages" / "shared" / "data-rights.ts"

# Ordered set of vocabulary keys the JSON must declare (the enumerated
# vocabularies plus the record/table vocabularies). ``bindings`` must cover this
# exact set: nothing bound twice, nothing silently added.
VOCAB_KEYS = (
    "rightsDerivationClasses",
    "learningClasses",
    "ownershipClasses",
    "intelligenceRightsProfiles",
    "disclosureBoundaries",
    "olympusPurposes",
    "lifecycleActions",
    "modelRevocationStates",
    "rightsDecisionDispositions",
    "rightsProfileDefaults",
    "learningAuthorityFlags",
    "terminationAuthorityActions",
    "generalizationDestinations",
    "generalizationTransformations",
    "modelRevocationSemantics",
    "migrationMappings",
)

# Vocabulary keys that are bound to a python enum + TS twin array surface.
# Derived from the bindings block at runtime; this tuple is only the fallback so
# a malformed bindings block cannot silently skip a parity check.
EXPECTED_BOUND_KEYS = (
    "rightsDerivationClasses",
    "learningClasses",
    "ownershipClasses",
    "intelligenceRightsProfiles",
    "disclosureBoundaries",
    "olympusPurposes",
    "lifecycleActions",
    "modelRevocationStates",
    "rightsDecisionDispositions",
)

_LOWER_SNAKE_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")

ERRORS: list[str] = []


def err(msg: str) -> None:
    ERRORS.append(msg)


def _is_snake(value: object) -> bool:
    return isinstance(value, str) and bool(_LOWER_SNAKE_RE.fullmatch(value))


# ── Structural vocabulary checks ──────────────────────────────────────────────


def _require_snake_list(vocab: dict, key: str) -> list[str]:
    """Return the members of a lower_snake string-list vocabulary key."""
    value = vocab.get(key)
    if not isinstance(value, list) or not value:
        err(f"vocabulary: {key!r} must be a non-empty list")
        return []
    if not all(isinstance(v, str) for v in value):
        err(f"vocabulary: {key!r} must contain only strings")
        return [v for v in value if isinstance(v, str)]
    if len(set(value)) != len(value):
        err(f"vocabulary: {key!r} contains duplicates")
    for v in value:
        if not _is_snake(v):
            err(f"vocabulary: {key!r} value {v!r} is not lower_snake")
    return list(value)


def _check_profiles(vocab: dict) -> None:
    profiles = vocab.get("intelligenceRightsProfiles")
    defaults = vocab.get("rightsProfileDefaults")
    profile_set = set(profiles) if isinstance(profiles, list) else set()
    if not isinstance(defaults, dict) or not defaults:
        err("vocabulary: 'rightsProfileDefaults' must be a non-empty object")
        return
    if set(defaults) != profile_set:
        err(
            f"vocabulary: rightsProfileDefaults keys {sorted(defaults)} != "
            f"intelligenceRightsProfiles {sorted(profile_set)}"
        )
    expected_fields = {
        "generated_output_retention": str,
        "generalized_learning": bool,
        "olympus_internal_intelligence": bool,
        "contributed_model_training": bool,
    }
    for profile, record in defaults.items():
        if not isinstance(record, dict):
            err(f"vocabulary: rightsProfileDefaults.{profile} must be an object")
            continue
        for field, field_type in expected_fields.items():
            if field not in record:
                err(f"vocabulary: rightsProfileDefaults.{profile} missing {field!r}")
            elif not isinstance(record[field], field_type):
                err(
                    f"vocabulary: rightsProfileDefaults.{profile}.{field} must be a "
                    f"{field_type.__name__}"
                )
        if not isinstance(record.get("generated_output_retention"), str) or not record.get(
            "generated_output_retention"
        ):
            err(
                f"vocabulary: rightsProfileDefaults.{profile}.generated_output_retention "
                "must be a non-empty string"
            )


def _check_learning_authority_flags(vocab: dict) -> None:
    learning = vocab.get("learningClasses")
    flags = vocab.get("learningAuthorityFlags")
    learning_set = set(learning) if isinstance(learning, list) else set()
    if not isinstance(flags, list) or not flags:
        err("vocabulary: 'learningAuthorityFlags' must be a non-empty list")
        return
    if not all(isinstance(f, str) and _is_snake(f) for f in flags):
        err("vocabulary: learningAuthorityFlags must be lower_snake strings")
    if set(flags) != learning_set:
        err(
            f"vocabulary: learningAuthorityFlags {sorted(flags)} != learningClasses "
            f"{sorted(learning_set)} (every learning class has an authority flag)"
        )


def _check_termination_actions(vocab: dict) -> None:
    actions = vocab.get("terminationAuthorityActions")
    if not isinstance(actions, dict) or not actions:
        err("vocabulary: 'terminationAuthorityActions' must be a non-empty object")
        return
    for artifact, disposition in actions.items():
        if not _is_snake(artifact):
            err(f"vocabulary: terminationAuthorityActions key {artifact!r} is not lower_snake")
        if not isinstance(disposition, str) or not _is_snake(disposition):
            err(
                f"vocabulary: terminationAuthorityActions[{artifact!r}] disposition "
                f"{disposition!r} must be a lower_snake string"
            )


def _check_migration(vocab: dict) -> None:
    learning = set(vocab.get("learningClasses", [])) if isinstance(
        vocab.get("learningClasses"), list
    ) else set()
    semantics = vocab.get("modelRevocationSemantics")
    if isinstance(semantics, dict):
        for field in ("legacyBoolean", "mapsTo"):
            if not isinstance(semantics.get(field), str) or not semantics[field]:
                err(f"vocabulary: modelRevocationSemantics.{field} must be a non-empty string")
        if not isinstance(semantics.get("broadens"), bool):
            err("vocabulary: modelRevocationSemantics.broadens must be a boolean")
        if semantics.get("mapsTo") not in learning:
            err(
                f"vocabulary: modelRevocationSemantics.mapsTo {semantics.get('mapsTo')!r} "
                "must be a learningClasses member"
            )
        if semantics.get("legacyBoolean") == semantics.get("mapsTo"):
            err(
                f"vocabulary: modelRevocationSemantics legacyBoolean {semantics.get('legacyBoolean')!r} "
                "must differ from mapsTo"
            )
        if semantics.get("broadens") is not False:
            err(
                "vocabulary: modelRevocationSemantics.broadens must be false "
                "(the legacy field must not broaden silently)"
            )
    else:
        err("vocabulary: 'modelRevocationSemantics' must be an object")

    mappings = vocab.get("migrationMappings")
    if not isinstance(mappings, list) or not mappings:
        err("vocabulary: 'migrationMappings' must be a non-empty list")
        return
    legacy_seen: set[str] = set()
    for mapping in mappings:
        if not isinstance(mapping, dict):
            err("vocabulary: migrationMappings entries must be objects")
            continue
        for field in ("legacyBoolean", "mapsTo"):
            if not isinstance(mapping.get(field), str) or not mapping[field]:
                err(f"vocabulary: migrationMappings entry missing non-empty {field!r}")
        if not isinstance(mapping.get("broadens"), bool):
            err("vocabulary: migrationMappings entry 'broadens' must be a boolean")
            continue
        legacy = mapping.get("legacyBoolean")
        if isinstance(legacy, str):
            if legacy in legacy_seen:
                err(f"vocabulary: migrationMappings maps legacy field {legacy!r} twice")
            legacy_seen.add(legacy)
        if mapping.get("mapsTo") not in learning:
            err(
                f"vocabulary: migrationMappings mapsTo {mapping.get('mapsTo')!r} "
                "must be a learningClasses member"
            )
        if mapping.get("broadens") is not False:
            err(
                "vocabulary: migrationMappings.broadens must be false "
                "(the legacy field must not broaden silently)"
            )
    if isinstance(semantics, dict):
        first = mappings[0] if isinstance(mappings[0], dict) else {}
        if semantics != first:
            err(
                "vocabulary: modelRevocationSemantics must equal migrationMappings[0] "
                "(both present the same single legacy mapping)"
            )


def _check_bindings(vocab: dict) -> None:
    """Every vocabulary key must be bound or allowlisted, exactly once."""
    bindings = vocab.get("bindings")
    if not isinstance(bindings, dict):
        err("vocabulary: 'bindings' must be an object")
        return
    entries = {k: v for k, v in bindings.items() if not k.startswith("_")}
    if set(entries) != set(VOCAB_KEYS):
        err(
            f"vocabulary: bindings must cover exactly {sorted(VOCAB_KEYS)} "
            f"(got {sorted(entries)}, missing {sorted(set(VOCAB_KEYS) - set(entries))}, "
            f"extra {sorted(set(entries) - set(VOCAB_KEYS))})"
        )
    for key in VOCAB_KEYS:
        entry = entries.get(key)
        if not isinstance(entry, dict):
            err(f"vocabulary: bindings[{key!r}] must be an object")
            continue
        bound = isinstance(entry.get("pythonEnum"), str) and bool(entry.get("pythonEnum"))
        has_ts = isinstance(entry.get("tsArray"), str) and bool(entry.get("tsArray"))
        allowlisted = entry.get("allowlisted") is True
        if bound != has_ts:
            err(
                f"vocabulary: bindings[{key!r}] must declare pythonEnum AND tsArray "
                "together (bound) or neither (allowlisted)"
            )
        if bound and allowlisted:
            err(f"vocabulary: bindings[{key!r}] cannot be both bound and allowlisted")
        if allowlisted:
            if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
                err(f"vocabulary: bindings[{key!r}] allowlisted entry needs a 'reason'")
        elif not bound:
            err(
                f"vocabulary: bindings[{key!r}] must be bound "
                "(pythonEnum + tsArray) or allowlisted"
            )


def validate_vocabulary(vocab: dict) -> dict:
    """Structural checks; returns {key: members} for the bound list keys."""
    if vocab.get("schemaVersion") != "2.0.0":
        err("vocabulary: schemaVersion must be \"2.0.0\"")
    if vocab.get("contractVersion") != "8.12.0":
        err("vocabulary: contractVersion must be \"8.12.0\"")
    if not isinstance(vocab.get("description"), str) or not vocab["description"].strip():
        err("vocabulary: description must be a non-empty string")

    registered = vocab.get("registeredCanonicalVocabularies")
    if not isinstance(registered, list):
        err("vocabulary: registeredCanonicalVocabularies must be a list")
    elif not all(isinstance(p, str) for p in registered):
        err("vocabulary: registeredCanonicalVocabularies entries must be path strings")

    for key in VOCAB_KEYS:
        if key not in vocab:
            err(f"vocabulary: missing vocabulary key {key!r}")

    members: dict[str, list[str]] = {}
    for key in ("rightsDerivationClasses", "learningClasses", "ownershipClasses",
                "intelligenceRightsProfiles", "disclosureBoundaries", "olympusPurposes",
                "lifecycleActions", "modelRevocationStates", "rightsDecisionDispositions",
                "generalizationDestinations", "generalizationTransformations"):
        if key in vocab:
            members[key] = _require_snake_list(vocab, key)

    _check_profiles(vocab)
    _check_learning_authority_flags(vocab)
    _check_termination_actions(vocab)
    _check_migration(vocab)
    _check_bindings(vocab)
    return members


# ── Python side (AST) ────────────────────────────────────────────────────────


def _is_enum_class(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = getattr(base, "id", None) or getattr(base, "attr", None)
        if name == "Enum":
            return True
    return False


def _enum_member_names_and_values(class_node: ast.ClassDef) -> dict[str, Optional[str]]:
    """Return {member NAME: explicit string value or None} for an Enum class body."""
    out: dict[str, Optional[str]] = {}
    for stmt in class_node.body:
        targets: list[ast.expr] = []
        value_node: Optional[ast.expr] = None
        if isinstance(stmt, ast.Assign):
            targets = list(stmt.targets)
            value_node = stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
            value_node = stmt.value
        if len(targets) == 1 and isinstance(targets[0], ast.Name):
            value: Optional[str] = None
            if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
                value = value_node.value
            out[targets[0].id] = value
    return out


def _python_enum_values(path: Path, class_name: str) -> Optional[set[str]]:
    """Return the canonical (snake) value set of ``class_name`` or None if the
    enum class is absent from ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name and _is_enum_class(node):
            values: set[str] = set()
            for name, explicit in _enum_member_names_and_values(node).items():
                if explicit is None:
                    # UPPER_SNAKE member name -> snake canonical value
                    values.add(name.lower())
                else:
                    values.add(explicit)
            if not values:
                return set()
            return values
    return None


def check_python(models_path: Path, members: dict[str, list[str]], bindings: dict) -> None:
    if not models_path.is_file():
        err(
            f"python: models file missing: {models_path.relative_to(ROOT)} — the python-enum "
            "stream must land the Rights enums here"
        )
        return
    for key in EXPECTED_BOUND_KEYS:
        binding = (bindings.get(key) or {}) if isinstance(bindings, dict) else {}
        class_name = binding.get("pythonEnum") if isinstance(binding, dict) else None
        if not isinstance(class_name, str):
            continue  # binding-shape errors reported by the structural checks
        values = _python_enum_values(models_path, class_name)
        if values is None:
            err(
                f"python: Enum class {class_name!r} (binding for {key!r}) not found in "
                f"{models_path.relative_to(ROOT)}"
            )
            continue
        expected = set(members.get(key, []))
        missing = sorted(expected - values)
        extra = sorted(values - expected)
        if missing or extra:
            err(
                f"python: Enum {class_name}.members != vocabulary.{key} — "
                f"missing={missing}, extra={extra}"
            )


# ── TypeScript side (regex) ──────────────────────────────────────────────────


def _extract_ts_array(source: str, name: str) -> Optional[list[str]]:
    match = re.search(
        rf"\b{re.escape(name)}\b\s*(:\s*[^=\n]*?)?=\s*\[(.*?)\]",
        source,
        re.DOTALL,
    )
    if not match:
        return None
    body = match.group(2)
    literals = re.findall(r"""(['"])([a-z0-9_]+)\1""", body)
    return [item[1] for item in literals]


def check_typescript(ts_path: Path, members: dict[str, list[str]], bindings: dict) -> None:
    if not ts_path.is_file():
        err(
            f"typescript: twin file missing: {ts_path.relative_to(ROOT)} — the TS twin stream "
            "must land packages/shared/data-rights.ts"
        )
        return
    source = ts_path.read_text(encoding="utf-8")
    for key in EXPECTED_BOUND_KEYS:
        binding = (bindings.get(key) or {}) if isinstance(bindings, dict) else {}
        array_name = binding.get("tsArray") if isinstance(binding, dict) else None
        if not isinstance(array_name, str):
            continue
        literals = _extract_ts_array(source, array_name)
        if literals is None:
            err(
                f"typescript: array {array_name!r} (binding for {key!r}) not found in "
                f"{ts_path.relative_to(ROOT)}"
            )
            continue
        if len(set(literals)) != len(literals):
            err(f"typescript: array {array_name!r} contains duplicate literals")
        expected = set(members.get(key, []))
        actual = set(literals)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing or extra:
            err(
                f"typescript: array {array_name}.literals != vocabulary.{key} — "
                f"missing={missing}, extra={extra}"
            )


# ── Entry point ──────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI gate (default mode): exit 0 on parity, 1 on violation",
    )
    parser.add_argument(
        "--vocab",
        metavar="PATH",
        default=str(VOCAB_PATH),
        help="canonical vocabulary JSON (default packages/shared/contracts/rights-vocabulary.json)",
    )
    parser.add_argument(
        "--models",
        metavar="PATH",
        default=str(PY_MODELS_PATH),
        help="python models file to AST-parse (default data_rights/models.py)",
    )
    parser.add_argument(
        "--ts",
        metavar="PATH",
        default=str(TS_TWIN_PATH),
        help="TS twin file to regex-parse (default packages/shared/data-rights.ts)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    del ERRORS[:]
    args = _parse_args(argv)
    vocab_path = Path(args.vocab)
    if not vocab_path.is_file():
        err(f"vocabulary: missing {vocab_path.relative_to(ROOT)}")
        return 1
    try:
        vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        err(f"vocabulary: {vocab_path.relative_to(ROOT)} is not valid JSON: {exc}")
        return 1

    members = validate_vocabulary(vocab)
    bindings = vocab.get("bindings") if isinstance(vocab, dict) else {}
    check_python(Path(args.models), members, bindings)
    check_typescript(Path(args.ts), members, bindings)

    if ERRORS:
        print("rights-vocabulary validation FAILED:")
        for message in ERRORS:
            print(f"  - {message}")
        return 1

    bound = [k for k in VOCAB_KEYS if isinstance(bindings.get(k), dict)
             and isinstance(bindings[k].get("pythonEnum"), str)]
    print(
        f"rights-vocabulary: OK — schemaVersion 2.0.0 / contractVersion 8.12.0, "
        f"{len(members)} enumerated vocabularies, {len(bound)} python/TS-bound keys "
        f"({len(VOCAB_KEYS) - len(bound)} allowlisted), all three surfaces agree"
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
