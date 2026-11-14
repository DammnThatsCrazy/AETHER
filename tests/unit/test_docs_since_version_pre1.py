import importlib.util
from pathlib import Path

import pytest

_path = Path(__file__).resolve().parents[2] / "scripts" / "validate_frontmatter.py"
_spec = importlib.util.spec_from_file_location("validate_frontmatter", _path)
vf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vf)

_PROP = vf.load_schema()["properties"]["since_version"]


@pytest.mark.parametrize("value", ["0.1.0", "0.1.0-alpha.0", "0.5.0-beta.2", "0.12.3"])
def test_pre_1_0_versions_are_accepted(value):
    vf._validate_against(value, _PROP, "since_version")


@pytest.mark.parametrize("value", ["1.0.0", "8.12.0", "8.8.0", "13.0.0", "v0.1.0", "0.1"])
def test_post_1_0_and_malformed_versions_are_rejected(value):
    with pytest.raises(vf.ValidationError):
        vf._validate_against(value, _PROP, "since_version")
