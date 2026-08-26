#!/usr/bin/env python3
"""Fail closed when AWS and non-AWS apply inputs are incomplete.

The Terraform plan can contain resources managed by more than one provider.
AWS IAM credentials cannot authorize Auth0 resources, so the apply contract
must validate both surfaces before Terraform is allowed to run.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pathlib import Path

AWS_ROLE_RE = re.compile(r"^arn:aws:iam::\d{12}:role/[A-Za-z0-9+=,.@_-]{1,64}$")
AUTH0_TYPES = {"auth0_client", "auth0_client_grant", "auth0_connection", "auth0_resource_server", "auth0_connection_clients"}


def _decode_jwt_scope(token: str) -> set[str]:
    """Return the management scopes in a JWT without ever printing the token."""
    parts = token.split(".")
    if len(parts) != 3:
        return set()
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    scope = payload.get("scope", "")
    if not isinstance(scope, str):
        return set()
    return set(scope.split())


def verify_auth0_scopes(domain: str, client_id: str, client_secret: str, required: set[str]) -> list[str]:
    """Obtain a management token and fail closed when its scopes are incomplete."""
    host = domain.strip().rstrip("/")
    if not host.startswith("https://"):
        host = f"https://{host}"
    token_url = f"{host}/oauth/token"
    body = urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "audience": f"{host}/api/v2/",
        }
    ).encode()
    request = Request(token_url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(request, timeout=20) as response:
            token_response = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return [f"Auth0 management token request failed ({type(exc).__name__}); verify the tenant, client, secret, and grant"]

    if not isinstance(token_response, dict):
        return ["Auth0 management token response was not a JSON object"]
    access_token = token_response.get("access_token", "")
    if not isinstance(access_token, str):
        return ["Auth0 management token response contained an invalid access token"]
    if not access_token:
        return ["Auth0 management token response did not contain an access token"]
    granted = _decode_jwt_scope(access_token)
    if not granted:
        return ["Auth0 management token did not expose a readable scope claim; refusing to apply without scope verification"]
    missing = sorted(required - granted)
    if missing:
        return ["Auth0 management client is missing required scopes: " + ", ".join(missing)]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--verify-auth0-scopes", action="store_true")
    parser.add_argument("--auth0-scope-contract", type=Path, default=Path("config/staging_apply_iam_policy.yaml"))
    args = parser.parse_args()

    try:
        inventory = json.loads(args.inventory.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::cannot read provider inventory: {exc}")
        return 1

    resources = inventory.get("resources") or []
    types = {str(item.get("type")) for item in resources}
    errors: list[str] = []

    role = os.environ.get("AWS_TERRAFORM_APPLY_ROLE_ARN", "")
    if not AWS_ROLE_RE.fullmatch(role):
        errors.append("AWS_TERRAFORM_APPLY_ROLE_ARN must be a valid IAM role ARN")
    elif ":role/AetherStagingDeploy" not in role and "staging" in str(inventory.get("profile", "")):
        errors.append("staging apply must use the AetherStagingDeploy role")

    if types & AUTH0_TYPES:
        for name in ("AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET"):
            if not os.environ.get(name):
                errors.append(f"{name} required for Auth0 resources in the reviewed plan")
        if args.verify_auth0_scopes and not errors:
            try:
                import yaml
            except ImportError as exc:
                errors.append(f"cannot load Auth0 scope contract: {exc}")
            else:
                try:
                    contract = yaml.safe_load(args.auth0_scope_contract.read_text()) or {}
                    required_scopes = {
                        scope
                        for item in contract.get("external_provider_requirements", [])
                        if item.get("provider") == "auth0"
                        for scope in item.get("required_scopes", [])
                    }
                except (OSError, yaml.YAMLError) as exc:
                    errors.append(f"cannot load Auth0 scope contract: {exc}")
                else:
                    errors.extend(
                        verify_auth0_scopes(
                            os.environ["AUTH0_DOMAIN"],
                            os.environ["AUTH0_CLIENT_ID"],
                            os.environ["AUTH0_CLIENT_SECRET"],
                            required_scopes,
                        )
                    )

    if errors:
        for error in errors:
            print(f"::error::{error}")
        return 1

    provider_summary = "AWS only" if not (types & AUTH0_TYPES) else "AWS + Auth0"
    print(f"provider apply inputs validated: {provider_summary}; {len(resources)} resources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
