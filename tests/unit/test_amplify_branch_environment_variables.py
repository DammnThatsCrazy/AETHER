"""Contract checks for app-specific Amplify branch configuration."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TERRAFORM_MAIN = REPO_ROOT / "deploy/aws/terraform/main.tf"


def _branch_environment_variable_maps() -> tuple[str, str, str, str]:
    source = TERRAFORM_MAIN.read_text(encoding="utf-8")
    resource = re.search(
        r'^resource "aws_amplify_branch" "main" \{\n(?P<body>.*?)^\}',
        source,
        re.MULTILINE | re.DOTALL,
    )
    assert resource is not None, "the canonical Amplify branch resource must exist"

    assignment = re.search(
        r"^  environment_variables = merge\(\n(?P<body>.*?)^  \)\s*$",
        resource.group("body"),
        re.MULTILINE | re.DOTALL,
    )
    assert assignment is not None, "branch variables must merge common and app-specific maps"
    expression = assignment.group("body")

    common = re.search(
        r"^    \{\n(?P<body>.*?)^    \},\n    each\.key",
        expression,
        re.MULTILINE | re.DOTALL,
    )
    aether_app = re.search(
        r'^    each\.key == "aether-app" \? \{\n(?P<body>.*?)^    \} : \{\},$',
        expression,
        re.MULTILINE | re.DOTALL,
    )
    status = re.search(
        r'^    each\.key == "status" \? \{\n(?P<body>.*?)^    \} : \{\}\s*$',
        expression,
        re.MULTILINE | re.DOTALL,
    )
    assert common is not None, "all branches must receive the common variable map"
    assert aether_app is not None, "Aether auth variables must be restricted to aether-app"
    assert status is not None, "status URLs must be restricted to the status branch"
    return expression, common.group("body"), aether_app.group("body"), status.group("body")


def _keys(mapping: str) -> set[str]:
    return set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)\s*=", mapping, re.MULTILINE))


def _value(mapping: str, key: str) -> str:
    assignment = re.search(rf"^\s*{re.escape(key)}\s*=\s*(.+)$", mapping, re.MULTILINE)
    assert assignment is not None, f"{key} must be configured in its owning map"
    return assignment.group(1).strip()


def test_amplify_branches_receive_only_their_declared_variables() -> None:
    expression, common, aether_app, status = _branch_environment_variable_maps()

    assert _keys(common) == {"AETHER_ENV"}
    assert _value(common, "AETHER_ENV") == "var.environment"
    assert _keys(aether_app) == {
        "VITE_AETHER_ENV",
        "VITE_API_BASE_URL",
        "VITE_AETHER_ENDPOINT",
        "VITE_AUTH0_DOMAIN",
        "VITE_AUTH0_CLIENT_ID",
        "VITE_AUTH0_AUDIENCE",
        "VITE_AUTH0_REDIRECT_URI",
        "VITE_AUTH0_LOGOUT_URI",
    }
    assert _keys(status) == {
        "VITE_STATUS_API_URL",
        "VITE_STATUS_DOCS_URL",
        "VITE_STATUS_AETHER_MARKETING_URL",
    }
    assert ': ""' not in expression, "non-target branches must omit, not blank, app-specific keys"

    assert _value(aether_app, "VITE_AETHER_ENV") == "var.environment"
    assert _value(aether_app, "VITE_API_BASE_URL") == '"https://${var.domain_name}"'
    assert _value(aether_app, "VITE_AETHER_ENDPOINT") == '"https://${var.domain_name}"'
    assert _value(aether_app, "VITE_AUTH0_DOMAIN") == "var.auth0_domain"
    assert _value(aether_app, "VITE_AUTH0_CLIENT_ID") == "module.auth0.aether_client_id"
    assert _value(aether_app, "VITE_AUTH0_AUDIENCE") == "var.auth0_api_audience"
    assert _value(aether_app, "VITE_AUTH0_REDIRECT_URI") == '"${var.aether_app_url}/callback"'
    assert _value(aether_app, "VITE_AUTH0_LOGOUT_URI") == '"${var.aether_app_url}/login"'

    assert _value(status, "VITE_STATUS_API_URL") == "var.status_api_url"
    assert status.count('var.amplify_custom_domain_enabled && var.amplify_domain_name != ""') == 2
    assert '"https://docs.${var.amplify_domain_name}"' in status
    assert '"https://${aws_amplify_app.frontend["docs"].default_domain}"' in status
    assert '"https://aether.${var.amplify_domain_name}"' in status
    assert '"https://${aws_amplify_app.frontend["aether-marketing"].default_domain}"' in status
