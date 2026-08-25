#!/usr/bin/env python3
"""Fail closed when AWS and non-AWS apply inputs are incomplete.

The Terraform plan can contain resources managed by more than one provider.
AWS IAM credentials cannot authorize Auth0 resources, so the apply contract
must validate both surfaces before Terraform is allowed to run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

AWS_ROLE_RE = re.compile(r"^arn:aws:iam::\d{12}:role/[A-Za-z0-9+=,.@_-]{1,64}$")
AUTH0_TYPES = {"auth0_client", "auth0_client_grant", "auth0_connection", "auth0_resource_server", "auth0_connection_clients"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True, type=Path)
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

    if errors:
        for error in errors:
            print(f"::error::{error}")
        return 1

    provider_summary = "AWS only" if not (types & AUTH0_TYPES) else "AWS + Auth0"
    print(f"provider apply inputs validated: {provider_summary}; {len(resources)} resources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
