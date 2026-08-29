"""Platform-wide coverage guard: every legacy production_status.py AREA must map
to a real feature-readiness record, and the whole corpus must validate.

This is what keeps the multidimensional model extended across the ENTIRE
platform — adding a new AREA to the legacy scorecard without a matching readiness
record (or breaking an existing mapping) fails here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from scripts.lib.readiness_model import load_features
from scripts.migrate_readiness_data import _match_feature

ROOT = Path(__file__).resolve().parent.parent.parent


def _legacy_areas():
    spec = importlib.util.spec_from_file_location("ps_cov", ROOT / "scripts" / "production_status.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return [a.name for a in mod.AREAS]


def test_every_legacy_area_maps_to_a_record():
    records = {f.feature_id for f in load_features()}
    unmapped = []
    for name in _legacy_areas():
        fid = _match_feature(name)
        if fid is None or fid not in records:
            unmapped.append((name, fid))
    assert not unmapped, f"legacy areas without a readiness record: {unmapped}"


def test_platform_corpus_is_substantial():
    # The extension covers the whole platform, not a token few.
    assert len(load_features()) >= 30


def test_full_corpus_validates():
    from scripts.validate_readiness_model import main

    assert main([]) == 0
