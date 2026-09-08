"""TS <-> Python parity for the DataRightsGrant structured authorities.

`packages/shared/data-rights.ts` is the HAND-AUTHORED canonical TypeScript twin
(never generated) of the Python structured authorities that live in
`Backend Architecture/aether-backend/services/integrations/data_rights/models.py`
(frozen in docs/source-of-truth/RIGHTS_AUTHORITY_BLUEPRINT.md §3 and §5).

This test fails on drift in either direction:
  - the nine frozen vocabularies (rights derivation classes, learning classes,
    ownership classes, intelligence rights profiles, disclosure boundaries,
    Olympus purposes, lifecycle actions, model revocation states, rights
    decision dispositions) must match the Python `(str, Enum)` members
    value-for-value AND member-name-for-member-name (Python member name ==
    value.upper()); and
  - the nested pydantic model field sets for SourceUseAuthority,
    GeneratedOutputRights, LearningAuthority, DisclosureAuthority, and
    TerminationAuthority must match the TS interfaces field-for-field,
    order-insensitive, both directions.

Both files are read as text (no imports): the TS file cannot be imported from
pytest, and the Python twin may not be import-safe until its module graph is
complete. The test is fail-closed by construction — any drift surfaces here
with a message naming the offender on each side.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]

TS_PATH = REPO_ROOT / "packages" / "shared" / "data-rights.ts"
PY_PATH = (
    REPO_ROOT
    / "Backend Architecture"
    / "aether-backend"
    / "services"
    / "integrations"
    / "data_rights"
    / "models.py"
)

# The nine frozen vocabularies: TS `as const` array name -> Python Enum class name.
# These Python Enum class names are the parity contract the Python twin must use.
TS_VOCAB_TO_PY_ENUM: dict[str, str] = {
    "rightsDerivationClasses": "RightsDerivationClass",
    "learningClasses": "LearningClass",
    "ownershipClasses": "OwnershipClass",
    "intelligenceRightsProfiles": "IntelligenceRightsProfile",
    "disclosureBoundaries": "DisclosureBoundary",
    "olympusPurposes": "OlympusPurpose",
    "lifecycleActions": "LifecycleAction",
    "modelRevocationStates": "ModelRevocationState",
    "rightsDecisionDispositions": "RightsDecisionDisposition",
}

# Nested pydantic models whose field set must match the TS interface of the same
# name (both directions, order-insensitive).
PY_MODEL_PARITY: tuple[str, ...] = (
    "SourceUseAuthority",
    "GeneratedOutputRights",
    "LearningAuthority",
    "DisclosureAuthority",
    "TerminationAuthority",
)


# ── Parse the TypeScript side ────────────────────────────────────────────────

def _ts_vocab_array_values(array_name: str) -> list[str]:
    """Values of an `export const <array_name> = [...] as const` in data-rights.ts."""
    content = TS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"export const %s\s*=\s*\[(.*?)\]\s*as const" % array_name,
        content,
        re.DOTALL,
    )
    assert match, f"export const {array_name} = [...] as const not found in data-rights.ts"
    return re.findall(r"'([a-z_][a-z0-9_]*)'", match.group(1))


def _ts_interface_fields(interface_name: str) -> list[str]:
    """Field names of an `export interface <interface_name>`, in declaration order."""
    content = TS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"export interface %s\s*\{(.*?)\n\}" % interface_name,
        content,
        re.DOTALL,
    )
    assert match, f"export interface {interface_name} not found in data-rights.ts"
    return re.findall(r"^\s{2}([a-z_][a-z0-9_]*)\??:", match.group(1), re.M)


# ── Parse the Python mirror side ─────────────────────────────────────────────

def _py_enum_members(enum_name: str) -> list[tuple[str, str]]:
    """(member_name, value) pairs of a `class <enum_name>(str, Enum)` in models.py."""
    content = PY_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"class %s\(str, Enum\):(.*?)(?=\nclass |\n\ndef |\n__all__|\Z)" % enum_name,
        content,
        re.DOTALL,
    )
    assert match, f"class {enum_name}(str, Enum) not found in models.py"
    return re.findall(
        r"""^\s{4}([A-Z][A-Z0-9_]*)\s*=\s*["']([a-z_][a-z0-9_]*)["']""",
        match.group(1),
        re.M,
    )


def _py_model_fields(model_name: str) -> list[str]:
    """Field names declared on a `class <model_name>(BaseModel)` in models.py, in order."""
    content = PY_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"class %s\(BaseModel\):(.*?)(?=\nclass |\n\ndef |\n__all__|\Z)" % model_name,
        content,
        re.DOTALL,
    )
    assert match, f"class {model_name}(BaseModel) not found in models.py"
    return re.findall(r"^\s{4}([a-z_][a-z0-9_]*)\s*:", match.group(1), re.M)


# ── Tests: vocabulary parity ─────────────────────────────────────────────────

def test_nine_vocabularies_agree_value_for_value() -> None:
    """Each TS `as const` vocabulary and its Python Enum must carry the same values."""
    assert len(TS_VOCAB_TO_PY_ENUM) == 9, "The nine-vocabulary parity map drifted"
    for ts_name, py_enum in TS_VOCAB_TO_PY_ENUM.items():
        ts_values = _ts_vocab_array_values(ts_name)
        assert ts_values, f"TS vocabulary {ts_name} must not be empty"
        py_members = _py_enum_members(py_enum)
        assert py_members, f"Python enum {py_enum} must declare snake-valued members"
        py_values = [value for _name, value in py_members]
        assert ts_values == py_values, (
            f"Vocabulary {ts_name} <-> Python enum {py_enum} value drift.\n"
            f"  TS only:  {sorted(set(ts_values) - set(py_values))}\n"
            f"  Py only:  {sorted(set(py_values) - set(ts_values))}"
        )
        assert len(set(ts_values)) == len(ts_values), f"TS vocabulary {ts_name} must be unique"
        assert len(set(py_values)) == len(py_values), f"Python enum {py_enum} must be unique"


def test_python_enum_member_names_are_upper_snake_of_values() -> None:
    """Python member name == value.upper() (e.g. TENANT_ADAPTATION = 'tenant_adaptation')."""
    for _ts_name, py_enum in TS_VOCAB_TO_PY_ENUM.items():
        py_members = _py_enum_members(py_enum)
        assert py_members, f"Python enum {py_enum} must declare members"
        for member_name, value in py_members:
            assert member_name == value.upper(), (
                f"Python enum {py_enum} member {member_name} = {value!r} violates "
                f"the member-name == value.upper() convention: {value.upper()!r} != {member_name!r}"
            )


# ── Tests: nested pydantic model field-set parity ────────────────────────────

def test_nested_model_field_sets_agree_both_directions() -> None:
    """TS interface and Python pydantic model must name the same fields for each model."""
    for model_name in PY_MODEL_PARITY:
        ts_fields = _ts_interface_fields(model_name)
        py_fields = _py_model_fields(model_name)
        assert ts_fields, f"TS interface {model_name} must declare fields"
        assert py_fields, f"Python pydantic model {model_name} must declare fields"
        ts_set = set(ts_fields)
        py_set = set(py_fields)
        assert ts_set == py_set, (
            f"{model_name} field-set drift.\n"
            f"  TS only:  {sorted(ts_set - py_set)}\n"
            f"  Py only:  {sorted(py_set - ts_set)}"
        )


def test_nested_model_field_sets_have_expected_frozen_cardinality() -> None:
    """Guard each frozen model against accidental field widening on either side."""
    expected_cardinality = {
        "SourceUseAuthority": 6,
        "GeneratedOutputRights": 5,
        "LearningAuthority": 9,
        "DisclosureAuthority": 6,
        "TerminationAuthority": 10,  # actions + nine typed §14 keys
    }
    for model_name, expected_len in expected_cardinality.items():
        ts_fields = _ts_interface_fields(model_name)
        py_fields = _py_model_fields(model_name)
        assert len(ts_fields) == expected_len, (
            f"TS interface {model_name} has {len(ts_fields)} fields; frozen contract "
            f"enumerates {expected_len}: {ts_fields}"
        )
        assert len(py_fields) == expected_len, (
            f"Python model {model_name} has {len(py_fields)} fields; frozen contract "
            f"enumerates {expected_len}: {py_fields}"
        )
