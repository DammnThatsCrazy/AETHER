"""Unit tests for scripts/validate_frontmatter.py.

Covers the validator's positive path (valid frontmatter), negative paths
(every kind of schema violation it should catch), and edge cases
(missing frontmatter, empty frontmatter, malformed YAML, non-string
schema fields).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "validate_frontmatter.py"
SCHEMA = ROOT / "scripts" / "docs_schema.json"


@pytest.fixture(scope="module")
def vf():
    spec = importlib.util.spec_from_file_location("validate_frontmatter", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_frontmatter"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def schema():
    with SCHEMA.open() as fh:
        return json.load(fh)


# --- extract_frontmatter ----------------------------------------------------


def test_extract_frontmatter_returns_dict_when_present(vf):
    text = "---\ntitle: Hello\nslug: hello\n---\n\n# Body"
    assert vf.extract_frontmatter(text) == {"title": "Hello", "slug": "hello"}


def test_extract_frontmatter_returns_none_when_absent(vf):
    assert vf.extract_frontmatter("# No frontmatter here") is None


def test_extract_frontmatter_returns_empty_dict_for_empty_block(vf):
    assert vf.extract_frontmatter("---\n\n---\n\nbody") == {}


def test_extract_frontmatter_rejects_malformed_yaml(vf):
    with pytest.raises(vf.ValidationError):
        vf.extract_frontmatter("---\ntitle: : :\n---\n")


def test_extract_frontmatter_rejects_non_mapping(vf):
    with pytest.raises(vf.ValidationError):
        vf.extract_frontmatter("---\n- just\n- a list\n---\n")


# --- validate_frontmatter positive path -------------------------------------


def _minimal_valid_payload() -> dict:
    return {
        "title": "Anything",
        "slug": "section/anything",
        "section": "concepts",
        "visibility": "P",
        "audience": ["dev-junior"],
    }


def test_minimal_payload_validates(vf, schema):
    vf.validate_frontmatter(_minimal_valid_payload(), schema)  # no raise


def test_full_payload_validates(vf, schema):
    payload = _minimal_valid_payload() | {
        "status": "stable",
        "since_version": "8.8.0",
        "source_files": ["packages/shared/events.ts"],
        "flags": ["IG_X402_LAYER"],
        "prereqs": ["concepts/hybrid-model"],
        "related": ["api/ingestion"],
        "canonical_owner": "sdk@aether",
        "estimated_read_minutes": 5,
        "toc_depth": 3,
        "last_synced_commit": "abc1234",
    }
    vf.validate_frontmatter(payload, schema)  # no raise


# --- validate_frontmatter required fields -----------------------------------


@pytest.mark.parametrize("missing", ["title", "slug", "section", "visibility", "audience"])
def test_missing_required_field_fails(vf, schema, missing):
    payload = _minimal_valid_payload()
    del payload[missing]
    with pytest.raises(vf.ValidationError, match=f"missing required key '{missing}'"):
        vf.validate_frontmatter(payload, schema)


# --- validate_frontmatter enums ---------------------------------------------


def test_invalid_visibility_fails(vf, schema):
    payload = _minimal_valid_payload() | {"visibility": "BOGUS"}
    with pytest.raises(vf.ValidationError, match="visibility"):
        vf.validate_frontmatter(payload, schema)


def test_invalid_section_fails(vf, schema):
    payload = _minimal_valid_payload() | {"section": "made-up"}
    with pytest.raises(vf.ValidationError, match="section"):
        vf.validate_frontmatter(payload, schema)


def test_invalid_audience_persona_fails(vf, schema):
    payload = _minimal_valid_payload() | {"audience": ["everyone"]}
    with pytest.raises(vf.ValidationError, match=r"audience\[0\]"):
        vf.validate_frontmatter(payload, schema)


def test_invalid_status_fails(vf, schema):
    payload = _minimal_valid_payload() | {"status": "shipped"}
    with pytest.raises(vf.ValidationError, match="status"):
        vf.validate_frontmatter(payload, schema)


# --- validate_frontmatter patterns ------------------------------------------


def test_slug_must_be_url_safe(vf, schema):
    payload = _minimal_valid_payload() | {"slug": "Has Spaces"}
    with pytest.raises(vf.ValidationError, match="slug"):
        vf.validate_frontmatter(payload, schema)


def test_slug_uppercase_rejected(vf, schema):
    payload = _minimal_valid_payload() | {"slug": "Sdks/Web"}
    with pytest.raises(vf.ValidationError, match="slug"):
        vf.validate_frontmatter(payload, schema)


def test_since_version_must_be_semver(vf, schema):
    payload = _minimal_valid_payload() | {"since_version": "v8"}
    with pytest.raises(vf.ValidationError, match="since_version"):
        vf.validate_frontmatter(payload, schema)


def test_flag_must_be_screaming_snake(vf, schema):
    payload = _minimal_valid_payload() | {"flags": ["lower_case_flag"]}
    with pytest.raises(vf.ValidationError, match=r"flags\[0\]"):
        vf.validate_frontmatter(payload, schema)


def test_last_synced_commit_must_be_hex(vf, schema):
    payload = _minimal_valid_payload() | {"last_synced_commit": "not-a-sha"}
    with pytest.raises(vf.ValidationError, match="last_synced_commit"):
        vf.validate_frontmatter(payload, schema)


# --- validate_frontmatter types and bounds ----------------------------------


def test_audience_must_be_array(vf, schema):
    payload = _minimal_valid_payload() | {"audience": "dev-junior"}
    with pytest.raises(vf.ValidationError, match="audience"):
        vf.validate_frontmatter(payload, schema)


def test_audience_must_be_non_empty(vf, schema):
    payload = _minimal_valid_payload() | {"audience": []}
    with pytest.raises(vf.ValidationError, match="audience"):
        vf.validate_frontmatter(payload, schema)


def test_audience_rejects_duplicates(vf, schema):
    payload = _minimal_valid_payload() | {"audience": ["dev-junior", "dev-junior"]}
    with pytest.raises(vf.ValidationError, match="audience"):
        vf.validate_frontmatter(payload, schema)


def test_toc_depth_bounds(vf, schema):
    payload = _minimal_valid_payload() | {"toc_depth": 7}
    with pytest.raises(vf.ValidationError, match="toc_depth"):
        vf.validate_frontmatter(payload, schema)
    payload["toc_depth"] = 0
    with pytest.raises(vf.ValidationError, match="toc_depth"):
        vf.validate_frontmatter(payload, schema)


def test_estimated_read_minutes_rejects_boolean(vf, schema):
    # bool is a subclass of int in Python; the schema says integer so the
    # validator must explicitly reject booleans.
    payload = _minimal_valid_payload() | {"estimated_read_minutes": True}
    with pytest.raises(vf.ValidationError, match="estimated_read_minutes"):
        vf.validate_frontmatter(payload, schema)


def test_title_must_be_non_empty_string(vf, schema):
    payload = _minimal_valid_payload() | {"title": ""}
    with pytest.raises(vf.ValidationError, match="title"):
        vf.validate_frontmatter(payload, schema)


# --- additionalProperties ---------------------------------------------------


def test_unknown_key_rejected(vf, schema):
    payload = _minimal_valid_payload() | {"unknown_key": "value"}
    with pytest.raises(vf.ValidationError, match="unknown key"):
        vf.validate_frontmatter(payload, schema)
