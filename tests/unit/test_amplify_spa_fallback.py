"""Client-routed Amplify apps must fall back to index.html only for missing files.

A plain "200" rewrite of "/<*>" to "/index.html" also captures the built
bundles (/assets/*.js, *.css), so the browser receives HTML instead of code
and the staging app and docs rendered blank. "404-200" serves index.html only
when no file exists at the requested path.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN_TF = ROOT / "deploy/aws/terraform/main.tf"


def _custom_rules() -> str:
    text = MAIN_TF.read_text(encoding="utf-8")
    start = text.index("amplify_custom_rules = {")
    return text[start:text.index("\n  }\n", start)]


def test_catch_all_rewrites_never_shadow_built_assets():
    block = _custom_rules()
    catch_alls = re.findall(r'source\s*=\s*"/<\*>"[^}]*status\s*=\s*"([^"]+)"', block)
    assert catch_alls, "expected the client-routed apps to keep an index fallback"
    assert set(catch_alls) == {"404-200"}


def test_client_routed_apps_keep_their_index_fallback():
    block = _custom_rules()
    for app in ('"aether-app"', "docs"):
        section = block[block.index(f"{app} = ["):]
        section = section[:section.index("]")]
        assert '"/<*>"' in section and '"404-200"' in section, app
