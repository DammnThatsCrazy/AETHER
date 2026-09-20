#!/usr/bin/env python3
"""Probe the unauthenticated edge of the deployed Kyber OIDC flow.

The probe does not log in, exchange a code, or read a secret. It follows no
redirect. It only verifies that the live API emits a Google authorization
request with a non-empty public client id, PKCE/state/nonce, the exact API
callback URI, and the reviewed Workspace hosted-domain hint.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from check_kyber_staging_contract import _origin, validate_contract


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None


def _live_origin(value: str) -> str:
    candidate = value.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    return _origin(candidate, name="live API URL")


def probe(base_url: str) -> dict[str, object]:
    contract = validate_contract(require_public_client_id=False)
    api_origin = _live_origin(base_url)
    if api_origin != contract["api_origin"]:
        raise ValueError("live API URL does not match the reviewed TF_DOMAIN_NAME origin")

    request = Request(
        f"{api_origin}/v1/kyber/auth/login",
        headers={"Accept": "text/html,application/xhtml+xml"},
        method="GET",
    )
    try:
        response = build_opener(_NoRedirect()).open(request, timeout=20)
        status = response.status
        location = response.headers.get("Location", "")
    except HTTPError as exc:
        status = exc.code
        location = exc.headers.get("Location", "")
    except URLError as exc:
        raise ValueError(f"live Kyber login endpoint is unreachable: {exc.reason}") from exc

    if status != 307:
        raise ValueError(f"Kyber login endpoint returned HTTP {status}, expected 307")
    parsed = urlsplit(location)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {
        "accounts.google.com",
        "oauth2.googleapis.com",
    }:
        raise ValueError("Kyber login did not redirect to the approved Google authorization host")
    if parsed.path != "/o/oauth2/v2/auth":
        raise ValueError("Kyber login used an unexpected Google authorization endpoint")

    params = parse_qs(parsed.query, keep_blank_values=True)
    required = ("client_id", "state", "nonce", "code_challenge", "redirect_uri")
    missing = [name for name in required if not params.get(name) or not params[name][0]]
    if missing:
        raise ValueError("Kyber login authorization request is missing required OIDC parameters")
    if params.get("redirect_uri", [""])[0] != contract["google_redirect_uri"]:
        raise ValueError("live Google redirect_uri does not match the reviewed API callback")
    if params.get("code_challenge_method", [""])[0] != "S256":
        raise ValueError("Kyber login did not use S256 PKCE")
    if params.get("hd", [""])[0] != contract["google_hosted_domain"]:
        raise ValueError("live Google hosted-domain hint does not match the reviewed Workspace domain")
    if "client_secret" in params:
        raise ValueError("Kyber login leaked a client secret into the browser authorization request")

    return {
        "contract": "kyber-workforce-identity-live-probe",
        "version": 1,
        "api_origin": api_origin,
        "status": status,
        "provider_host": parsed.netloc.lower(),
        "authorization_path": parsed.path,
        "has_client_id": True,
        "has_state": True,
        "has_nonce": True,
        "has_pkce": True,
        "redirect_uri_matches": True,
        "hosted_domain_matches": True,
        "client_secret_in_request": False,
        "secret_values_read": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--evidence-out", type=Path)
    args = parser.parse_args(argv)
    try:
        evidence = probe(args.base_url)
    except ValueError as exc:
        print(f"::error::Kyber live identity probe failed: {exc}", file=sys.stderr)
        return 1
    if args.evidence_out:
        args.evidence_out.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(
        "Kyber live identity probe passed: "
        f"status={evidence['status']} provider={evidence['provider_host']} "
        "callback_matches=true pkce=true hosted_domain_matches=true "
        "secret_values_read=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
