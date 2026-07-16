#!/usr/bin/env python3
"""Fail closed when deployable runtime topology drifts from runtime roles."""
from __future__ import annotations

import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard, repo_root  # noqa: E402


def _runtime_roles() -> set[str]:
    path = repo_root() / "Backend Architecture/aether-backend/services/runtime/roles.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    workers: set[str] | None = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "WORKER_ROLES" and isinstance(node.value, ast.Call):
                workers = set(ast.literal_eval(node.value.args[0]))
            if node.target.id == "ALL_ROLES" and workers is not None:
                # Canonical source deliberately defines ALL_ROLES as
                # WORKER_ROLES | {"api", "all"}; do not import backend code.
                if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.BitOr):
                    return workers | set(ast.literal_eval(node.value.right))
    raise ValueError("canonical WORKER_ROLES/ALL_ROLES definitions not found")


def check() -> int:
    r = Reporter("DELIVERY TOPOLOGY — profile roles and immutable delivery")
    data = load_yaml("config/runtime_deployment.yaml")
    profiles = (data or {}).get("profiles", {})
    runtime = _runtime_roles()
    deployable = runtime - {"all"}
    for name in ("staging", "production-lean", "production-scale", "enterprise-isolated"):
        profile = profiles.get(name, {})
        roles = set((profile.get("roles") or {}).keys())
        r.require(roles == deployable,
                  f"{name}: every canonical role has exactly one deployment owner",
                  f"{name}: role mismatch missing={sorted(deployable-roles)} extra={sorted(roles-deployable)}")
        r.require("all" not in roles, f"{name}: role all rejected", f"{name}: role all is deployable")
        r.require((profile.get("roles", {}).get("api") or {}).get("public") is True,
                  f"{name}: API is explicit public role", f"{name}: API public ownership missing")
    lean = profiles.get("production-lean", {})
    r.require(lean.get("static_frontends") is True and lean.get("remote_ml") is False,
              "production-lean uses static frontends and inline ML",
              "production-lean topology violates cost policy")
    terraform = (repo_root() / "AWS Deployment/aether-aws/terraform/modules/ecs/main.tf").read_text(encoding="utf-8")
    r.require('resource "aws_ecs_service" "runtime_role"' in terraform and 'for_each        = var.runtime_roles' in terraform,
              "Terraform provisions every dedicated runtime-role service",
              "Terraform does not provision the runtime-role service topology")
    r.require(":latest" not in terraform and '@${var.backend_image_digest}' in terraform,
              "Terraform task definitions use immutable image digests",
              "Terraform task definitions contain mutable image references")
    workflow = (repo_root() / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    r.require(":latest" not in workflow, "workflow has no mutable latest reference", "deploy workflow uses :latest")
    r.require("|| 'production'" not in workflow and "default: production" not in workflow,
              "workflow never defaults an absent input to production",
              "workflow contains an automatic production default")
    r.require("force-new-deployment" not in workflow,
              "workflow registers exact task revisions", "workflow uses force-new-deployment")
    return r.finish()


if __name__ == "__main__":
    main_guard(check)
