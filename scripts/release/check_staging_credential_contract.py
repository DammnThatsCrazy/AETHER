#!/usr/bin/env python3
"""Validate the shape and scope of credentials needed by staging workflows.

This is deliberately a metadata/shape check.  It never calls a provider API,
prints a credential value, or attempts authentication.  AWS and GitHub
credentials are still verified at their real workflow boundaries; this gate
prevents an incomplete secret set or an obviously wrong host/ARN from reaching
those boundaries and failing after a plan or release has started.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Mapping


ROLE_RE = re.compile(r"^arn:aws:iam::\d{12}:role/[A-Za-z0-9+=,.@_/-]+$")
HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")
URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(?::\d+)?(?:/[^\s]*)?$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ACM_RE = re.compile(r"^arn:aws:acm:us-east-1:\d{12}:certificate/[0-9a-f-]+$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


ROLE_VARS = (
    "AWS_INFRA_ROLE_ARN",
    "AWS_TERRAFORM_PLAN_ROLE_ARN",
    "AWS_TERRAFORM_APPLY_ROLE_ARN",
    "AWS_DEPLOY_ROLE_ARN",
    "AWS_STAGING_LIFECYCLE_ROLE_ARN",
    "AWS_STAGING_SECRET_PREFLIGHT_ROLE_ARN",
)
COMMON_VARS = (
    "TF_STATE_BUCKET",
    "TF_LOCK_TABLE",
    "TF_ACM_CERTIFICATE_ARN",
    "TF_DOMAIN_NAME",
    "TF_ALERT_EMAIL",
    "TF_AUTH0_DOMAIN",
    "TF_AUTH0_MANAGEMENT_CLIENT_ID",
    "TF_AUTH0_MANAGEMENT_CLIENT_SECRET",
    "TF_AMPLIFY_GITHUB_ACCESS_TOKEN",
    "TF_AETHER_APP_URL",
    "TF_KYBER_APP_URL",
)
PILOT_SECRET_VARS = (
    "STAGING_ADMIN_API_KEY",
    "SMOKE_API_KEY",
)
FULL_GOOGLE_VARS = (
    "KYBER_GOOGLE_CLIENT_ID",
    "KYBER_GOOGLE_CLIENT_SECRET",
)


def _value(env: Mapping[str, str], name: str) -> str:
    return str(env.get(name, "")).strip()


def _require_nonempty(env: Mapping[str, str], names: tuple[str, ...], errors: list[str]) -> None:
    for name in names:
        if not _value(env, name):
            errors.append(f"missing credential {name}")


def credential_errors(
    *,
    lane: str,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    values = env if env is not None else os.environ
    errors: list[str] = []
    if lane not in {"full", "pilot"}:
        return [f"deployment lane must be full or pilot, got {lane!r}"]

    _require_nonempty(values, ROLE_VARS + COMMON_VARS, errors)
    if lane == "pilot":
        _require_nonempty(values, PILOT_SECRET_VARS, errors)
    else:
        _require_nonempty(values, FULL_GOOGLE_VARS, errors)

    for name in ROLE_VARS:
        value = _value(values, name)
        if value and not ROLE_RE.fullmatch(value):
            errors.append(f"{name} is not a concrete AWS IAM role ARN")

    domain = _value(values, "TF_DOMAIN_NAME")
    if domain and (domain.startswith("https://") or not HOST_RE.fullmatch(domain)):
        errors.append("TF_DOMAIN_NAME must be a hostname without a scheme or path")
    auth0_domain = _value(values, "TF_AUTH0_DOMAIN")
    if auth0_domain and (auth0_domain.startswith("https://") or not HOST_RE.fullmatch(auth0_domain)):
        errors.append("TF_AUTH0_DOMAIN must be a hostname without a scheme or path")

    for name in ("TF_AETHER_APP_URL", "TF_KYBER_APP_URL"):
        value = _value(values, name)
        if value and not URL_RE.fullmatch(value):
            errors.append(f"{name} must be an HTTPS URL")

    acm = _value(values, "TF_ACM_CERTIFICATE_ARN")
    if acm and not ACM_RE.fullmatch(acm):
        errors.append("TF_ACM_CERTIFICATE_ARN must be a us-east-1 ACM certificate ARN")
    email = _value(values, "TF_ALERT_EMAIL")
    if email and not EMAIL_RE.fullmatch(email):
        errors.append("TF_ALERT_EMAIL must be an email address")
    token = _value(values, "TF_AMPLIFY_GITHUB_ACCESS_TOKEN")
    if token and token == "-":
        errors.append("TF_AMPLIFY_GITHUB_ACCESS_TOKEN must be a real repository token")
    if token and any(char.isspace() for char in token):
        errors.append("TF_AMPLIFY_GITHUB_ACCESS_TOKEN must not contain whitespace")

    digest = _value(values, "TF_BACKEND_IMAGE_DIGEST")
    if digest and not DIGEST_RE.fullmatch(digest):
        errors.append("TF_BACKEND_IMAGE_DIGEST must be an immutable sha256 digest")

    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=("full", "pilot"), required=True)
    args = parser.parse_args(argv)
    errors = credential_errors(lane=args.lane)
    if errors:
        print("staging credential contract FAILED:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"staging credential contract valid: lane={args.lane}; values were not printed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
