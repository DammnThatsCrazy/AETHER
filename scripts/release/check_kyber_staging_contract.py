#!/usr/bin/env python3
"""Validate the repository-owned Kyber staging identity contract.

This checker deliberately reads configuration *metadata* only. It never calls
Secrets Manager and never accepts a Google client secret as an argument. The
secret values are mounted by ECS from the two reviewed ``aether/kyber-*``
secrets; the workflow that invokes this checker separately verifies that those
secret objects have an ``AWSCURRENT`` version.

The contract is shared by Terraform promotion, immutable SPA delivery, and
staging smoke/lifecycle workflows so an API/SPA callback drift cannot survive
until a browser tries to sign in.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit


CALLBACK_PATH = "/v1/kyber/auth/callback"
DEFAULT_HOSTED_DOMAIN = "olympuslabs.ai"
_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$")


def _origin(value: str, *, name: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"{name} must be an HTTPS origin without a path or credentials")
    return f"https://{parsed.netloc.lower()}"


def _domain(value: str) -> str:
    candidate = value.strip().lower().rstrip(".")
    if not candidate or not _DOMAIN_RE.fullmatch(candidate):
        raise ValueError("TF_DOMAIN_NAME must be a bare DNS host such as api.example.com")
    if not _HOST_RE.fullmatch(candidate):
        raise ValueError("TF_DOMAIN_NAME contains an invalid DNS host")
    return candidate


def _hosted_domain(value: str) -> str:
    candidate = value.strip().lower().rstrip(".")
    if not _DOMAIN_RE.fullmatch(candidate):
        raise ValueError("KYBER_GOOGLE_HOSTED_DOMAIN must be a concrete DNS domain")
    return candidate


def validate_contract(*, require_public_client_id: bool = False) -> dict[str, object]:
    """Return secret-free evidence or raise with a fail-closed explanation."""
    domain_value = os.environ.get("TF_DOMAIN_NAME", "").strip()
    if not domain_value:
        raise ValueError("TF_DOMAIN_NAME is required")
    domain = _domain(domain_value)
    expected_api = f"https://{domain}"

    kyber_value = os.environ.get("TF_KYBER_APP_URL", "").strip()
    if not kyber_value:
        raise ValueError("TF_KYBER_APP_URL is required")
    kyber_origin = _origin(kyber_value, name="TF_KYBER_APP_URL")

    configured_api = os.environ.get("KYBER_API_BASE_URL", "").strip()
    api_origin = _origin(configured_api, name="KYBER_API_BASE_URL") if configured_api else expected_api
    if api_origin != expected_api:
        raise ValueError("KYBER_API_BASE_URL must match https://TF_DOMAIN_NAME")

    expected_redirect = f"{api_origin}{CALLBACK_PATH}"
    configured_redirect = os.environ.get("KYBER_GOOGLE_REDIRECT_URI", "").strip()
    redirect_uri = configured_redirect or expected_redirect
    parsed_redirect = urlsplit(redirect_uri)
    if redirect_uri != expected_redirect or parsed_redirect.query or parsed_redirect.fragment:
        raise ValueError(
            "KYBER_GOOGLE_REDIRECT_URI must be the API origin plus "
            f"{CALLBACK_PATH}"
        )

    allowed_raw = os.environ.get("KYBER_ALLOWED_ORIGINS", "").strip()
    allowed_origins = [item.strip().rstrip("/") for item in allowed_raw.split(",") if item.strip()]
    if allowed_origins and allowed_origins != [kyber_origin]:
        raise ValueError("KYBER_ALLOWED_ORIGINS must contain exactly TF_KYBER_APP_URL")

    webauthn_origin = os.environ.get("KYBER_WEBAUTHN_ORIGIN", "").strip()
    if webauthn_origin and _origin(webauthn_origin, name="KYBER_WEBAUTHN_ORIGIN") != kyber_origin:
        raise ValueError("KYBER_WEBAUTHN_ORIGIN must match TF_KYBER_APP_URL")

    hosted_value = (
        os.environ.get("KYBER_GOOGLE_HOSTED_DOMAIN", "").strip()
        or os.environ.get("TF_KYBER_GOOGLE_HOSTED_DOMAIN", "").strip()
        or DEFAULT_HOSTED_DOMAIN
    )
    hosted_domain = _hosted_domain(hosted_value)

    client_id_present = bool(os.environ.get("KYBER_GOOGLE_CLIENT_ID", "").strip())
    if require_public_client_id and not client_id_present:
        raise ValueError(
            "KYBER_GOOGLE_CLIENT_ID is required for the Kyber SPA build; "
            "the value must match the ECS-mounted aether/kyber-google-client-id secret"
        )

    return {
        "contract": "kyber-workforce-identity",
        "version": 1,
        "profile": "staging",
        "api_origin": api_origin,
        "kyber_origin": kyber_origin,
        "google_redirect_uri": redirect_uri,
        "google_hosted_domain": hosted_domain,
        "allowed_origins": allowed_origins or [kyber_origin],
        "webauthn_origin": webauthn_origin or kyber_origin,
        "google_client_id_present": client_id_present,
        "google_client_secret_source": "aws_secrets_manager:aether/kyber-google-client-secret",
        "google_client_id_source": "aws_secrets_manager:aether/kyber-google-client-id",
        "secret_values_read": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-public-client-id",
        action="store_true",
        help="require the public Google client ID presence for an SPA build",
    )
    parser.add_argument("--evidence-out", type=Path)
    args = parser.parse_args(argv)

    try:
        evidence = validate_contract(require_public_client_id=args.require_public_client_id)
    except ValueError as exc:
        print(f"::error::Kyber staging contract invalid: {exc}", file=sys.stderr)
        return 1

    if args.evidence_out:
        args.evidence_out.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")

    print(
        "Kyber staging contract valid: "
        f"api_origin={evidence['api_origin']} "
        f"kyber_origin={evidence['kyber_origin']} "
        f"hosted_domain={evidence['google_hosted_domain']} "
        f"public_client_id_present={evidence['google_client_id_present']} "
        "secret_values_read=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
