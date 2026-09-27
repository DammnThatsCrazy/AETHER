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
    start = main.index("amplify_app_catalog = local.enable_static_frontends ? {")
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


def test_site_build_publishes_the_product_under_app() -> None:
    """One app per environment: the site's build also builds the product with
    base /app/ and copies it into the site's output at dist/app."""
    commands = _repository_spec()["frontend/site"]["frontend"]["phases"]["build"]["commands"]
    product = "VITE_BASE_PATH=/app/ npm run build --workspace=frontend/aether"
    assert product in commands
    assert commands.index("npm run build --workspace=frontend/site") < commands.index(product)
    assert "cp -R frontend/aether/dist/. frontend/site/dist/app/" in commands
    pre = _repository_spec()["frontend/site"]["frontend"]["phases"]["preBuild"]["commands"]
    assert "npm run build --workspace=packages/web" in pre
