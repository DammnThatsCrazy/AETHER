from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/check_provider_apply_inputs.py"


def _module():
    spec = importlib.util.spec_from_file_location("provider_apply_inputs", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(tmp_path: Path, resources: list[dict], **env: str) -> subprocess.CompletedProcess[str]:
    inventory = tmp_path / "resources.json"
    inventory.write_text(json.dumps({"profile": "staging", "resources": resources}))
    merged = os.environ.copy()
    merged.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--inventory", str(inventory)],
        text=True,
        capture_output=True,
        env=merged,
        check=False,
    )


def test_requires_aws_apply_role() -> None:
    result = run(Path("/tmp"), [], AWS_TERRAFORM_APPLY_ROLE_ARN="")
    assert result.returncode == 1
    assert "AWS_TERRAFORM_APPLY_ROLE_ARN" in result.stdout


def test_auth0_resources_require_auth0_credentials(tmp_path: Path) -> None:
    result = run(
        tmp_path,
        [{"type": "auth0_client"}],
        AWS_TERRAFORM_APPLY_ROLE_ARN="arn:aws:iam::544471417928:role/AetherStagingDeploy",
        AUTH0_DOMAIN="",
        AUTH0_CLIENT_ID="",
        AUTH0_CLIENT_SECRET="",
    )
    assert result.returncode == 1
    assert "AUTH0_CLIENT_SECRET" in result.stdout


def test_validates_both_provider_surfaces(tmp_path: Path) -> None:
    result = run(
        tmp_path,
        [{"type": "auth0_client"}],
        AWS_TERRAFORM_APPLY_ROLE_ARN="arn:aws:iam::544471417928:role/AetherStagingDeploy",
        AUTH0_DOMAIN="tenant.us.auth0.com",
        AUTH0_CLIENT_ID="client",
        AUTH0_CLIENT_SECRET="secret",
    )
    assert result.returncode == 0
    assert "AWS + Auth0" in result.stdout


def test_malformed_auth0_jwt_claims_fail_closed() -> None:
    module = _module()

    def token(payload: object) -> str:
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        return f"header.{encoded}.signature"

    assert module._decode_jwt_scope("not-a-jwt") == set()
    assert module._decode_jwt_scope(token(["not", "an", "object"])) == set()
    assert module._decode_jwt_scope(token({"scope": ["read:clients"]})) == set()
    assert module._decode_jwt_scope(token({"scope": "read:clients create:clients"})) == {
        "read:clients", "create:clients"
    }
