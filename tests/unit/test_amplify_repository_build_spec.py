"""Every Amplify app root Terraform can configure has a repository build spec.

Amplify uses the repository's amplify.yml over the console build spec. When
an app's appRoot is missing from it, the build fails before any command runs
("Invalid monorepo spec, no matching appRoot found in build spec"), as the
first staging build of frontend/site did.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _terraform_app_roots() -> set[str]:
    main = (ROOT / "deploy/aws/terraform/main.tf").read_text(encoding="utf-8")
    start = main.index("amplify_apps = local.enable_static_frontends ? {")
    block = main[start:main.index("\n  } : {}", start)]
    roots = set()
    for line in re.findall(r"^\s*app_root\s*=\s*(.+)$", block, re.MULTILINE):
        roots.update(re.findall(r'"(frontend/[a-z0-9-]+)"', line))
    return roots


def _repository_spec() -> dict[str, dict]:
    spec = yaml.safe_load((ROOT / "amplify.yml").read_text(encoding="utf-8"))
    return {app["appRoot"]: app for app in spec["applications"]}


def test_every_terraform_app_root_has_a_repository_build_spec() -> None:
    roots = _terraform_app_roots()
    assert {"frontend/site", "frontend/aether-marketing", "frontend/aether"} <= roots
    missing = roots - set(_repository_spec())
    assert not missing, f"amplify.yml has no application for {sorted(missing)}"


def test_each_build_spec_builds_and_publishes_its_own_workspace() -> None:
    for root, app in _repository_spec().items():
        frontend = app["frontend"]
        assert f"npm run build --workspace={root}" in frontend["phases"]["build"]["commands"], root
        assert frontend["artifacts"]["baseDirectory"] == f"{root}/dist", root
