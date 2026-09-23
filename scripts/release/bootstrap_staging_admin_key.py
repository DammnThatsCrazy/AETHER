#!/usr/bin/env python3
"""Preflight GitHub secret writes and safely verify/bootstrap the staging admin key.

Bootstrap candidates are written to the GitHub repository secret through
stdin before the one-time request. The helper never prints a key as ordinary
output or stores it in an artifact; after live admin verification it uses the
Actions mask command and GITHUB_ENV for later steps in the same job.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
STAGING_HOST_SUFFIX = ".staging.olympuslabsml.com"
STAGING_ADMIN_KEY_RE = re.compile(r"^ak_[A-Za-z0-9]{24}$")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not forward the bootstrap token or API key through a redirect."""

    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def _request(method: str, url: str, *, headers: dict[str, str], body: bytes | None = None):
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        try:
            return error.code, error.read()
        finally:
            error.close()


def _base_url_errors(base_url: str) -> list[str]:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return ["base URL must be an HTTPS staging API origin"]
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ["base URL must not contain credentials, query, or fragment data"]
    if not parsed.hostname.lower().endswith(STAGING_HOST_SUFFIX):
        return ["base URL host must be within the canonical staging domain"]
    if parsed.path not in ("", "/"):
        return ["base URL must be an origin without an API path"]
    return []


def _store_repository_secret(repo: str, api_key: str) -> bool:
    """Write the secret via stdin; never place the raw key in argv or output."""
    command = ["gh", "secret", "set", "STAGING_ADMIN_API_KEY", "--repo", repo]
    for attempt in range(3):
        result = subprocess.run(
            command,
            input=api_key + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return True
        if attempt < 2:
            time.sleep(1)
    return False


def _probe_repository_secret_write(repo: str) -> tuple[bool, str | None]:
    """Prove repo-secret write access before consuming the single-use route.

    The probe value is random and disposable. Its name is returned only when
    cleanup or the verification read cannot establish that it was removed.
    """
    name = f"AETHER_STAGING_BOOTSTRAP_PREFLIGHT_{secrets.token_hex(16).upper()}"
    value = secrets.token_urlsafe(32)
    existing_names = _repository_secret_names(repo)
    # Secret creation is an upsert, not a create-if-absent operation. Never
    # overwrite and later delete a pre-existing secret if a random name
    # collides, and fail closed if we cannot establish that the name is free.
    if existing_names is None or name in existing_names:
        return False, None

    set_result = subprocess.run(
        ["gh", "secret", "set", name, "--repo", repo],
        input=value + "\n",
        text=True,
        capture_output=True,
        check=False,
    )

    # A successful CLI exit is not enough evidence that the repository now
    # exposes the secret metadata. Confirm that the disposable name appeared
    # before deleting it; otherwise this probe could report a false positive.
    present_before_delete = _wait_for_repository_secret(repo, name, present=True)

    # Even an ambiguous set failure may have reached GitHub, so always attempt
    # to remove the random test secret before deciding whether bootstrap is safe.
    delete_result = None
    for attempt in range(3):
        delete_result = subprocess.run(
            ["gh", "secret", "delete", name, "--repo", repo],
            capture_output=True,
            text=True,
            check=False,
        )
        if delete_result.returncode == 0:
            break
        if attempt < 2:
            time.sleep(1)

    is_absent = _wait_for_repository_secret(repo, name, present=False)

    can_write = set_result.returncode == 0 and present_before_delete and is_absent
    return can_write, None if is_absent else name


def _repository_secret_names(repo: str) -> set[str] | None:
    """Return repository secret names only; never read their values."""
    result = subprocess.run(
        ["gh", "secret", "list", "--repo", repo, "--json", "name", "--jq", ".[].name"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return set((result.stdout or "").splitlines())


def _wait_for_repository_secret(repo: str, name: str, *, present: bool) -> bool:
    """Poll metadata briefly for a disposable secret write or deletion."""
    for attempt in range(3):
        names = _repository_secret_names(repo)
        if names is not None and ((name in names) is present):
            return True
        if attempt < 2:
            time.sleep(1)
    return False


def _gh_token_available() -> bool:
    """Require an explicitly selected PAT; never fall back to GITHUB_TOKEN."""
    return bool(os.environ.get("GH_TOKEN", "").strip())


def _github_cli_authenticated() -> bool:
    if not _gh_token_available():
        return False
    auth = subprocess.run(
        ["gh", "auth", "status", "--hostname", "github.com"],
        capture_output=True,
        text=True,
        check=False,
    )
    return auth.returncode == 0


def _preflight_repository_secret_write(repo: str) -> int:
    if not _gh_token_available():
        print(
            "error: GH_TOKEN must be set to WORKFLOW_DISPATCH_TOKEN or "
            "TF_AMPLIFY_GITHUB_ACCESS_TOKEN; GITHUB_TOKEN is not accepted for secret writes",
            file=sys.stderr,
        )
        return 2
    if not _github_cli_authenticated():
        print("error: configured GitHub token is not authenticated; no secret was changed", file=sys.stderr)
        return 2
    can_write, leftover_secret = _probe_repository_secret_write(repo)
    if not can_write:
        print(
            "error: repository-secret write access could not be verified safely; "
            "staging bootstrap remains blocked",
            file=sys.stderr,
        )
        if leftover_secret:
            print(f"error: verify and remove disposable secret {leftover_secret}", file=sys.stderr)
        return 2
    print("repository-secret write access verified; disposable secret removal confirmed")
    return 0


def _repository_secret_exists(repo: str) -> bool | None:
    """Check only secret names; never attempt to read their values."""
    result = subprocess.run(
        ["gh", "secret", "list", "--repo", repo, "--json", "name", "--jq", ".[].name"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return "STAGING_ADMIN_API_KEY" in (result.stdout or "").splitlines()


def _verify_admin_key(base_url: str, api_key: str) -> tuple[bool, str, int | None]:
    try:
        status, body = _request(
            "GET",
            f"{base_url}/v1/me",
            headers={"Accept": "application/json", "X-API-Key": api_key},
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return False, f"/v1/me could not be reached ({type(error).__name__})", None
    if status != 200:
        return False, f"/v1/me rejected the configured key with HTTP {status}", status
    try:
        payload = json.loads(body or b"{}")
    except (TypeError, ValueError):
        return False, "/v1/me returned a non-JSON response", status
    data = payload.get("data", payload) if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("tenant_id"), str):
        return False, "/v1/me response did not identify an authenticated tenant", status
    if data.get("is_admin") is not True:
        return False, "/v1/me authenticated but the key lacks admin scope", status
    return True, "", status


def _request_bootstrap(base_url: str, token: str, api_key: str) -> tuple[bool, str]:
    payload = json.dumps({
        "name": "Aether Staging Admin",
        "plan_tier": "alpha",
        "api_key": api_key,
    }).encode()
    last_failure = ""
    for attempt in range(5):
        try:
            status, body = _request(
                "POST",
                f"{base_url}/v1/auth/bootstrap/first-admin",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Aether-First-Admin-Bootstrap-Token": token,
                },
                body=payload,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            status, body = 0, b""
            last_failure = f"bootstrap request outcome was uncertain ({type(error).__name__})"

        if status == 200:
            try:
                response = json.loads(body or b"{}")
                data = response.get("data", response) if isinstance(response, dict) else None
                returned_key = data.get("api_key") if isinstance(data, dict) else None
            except (TypeError, ValueError):
                returned_key = None
            if returned_key == api_key:
                return True, ""
            return False, "bootstrap response did not confirm the pre-stored API key"

        if status and status < 500:
            if status == 409:
                return False, "bootstrap marker is bound to another request; no retry was attempted"
            return False, f"bootstrap returned HTTP {status}; inspect the response before continuing"

        if not last_failure:
            last_failure = f"bootstrap returned HTTP {status}"
        if attempt < 4:
            time.sleep(min(2 ** attempt, 8))
    return False, f"{last_failure}; the key remains stored and the same request can be resumed"


def _bootstrap_marker_state(
    base_url: str, token: str, candidate_key: str = ""
) -> tuple[bool, bool, str]:
    """Return (claimed, candidate_matches, error) without exposing key material."""
    headers = {
        "Accept": "application/json",
        "X-Aether-First-Admin-Bootstrap-Token": token,
    }
    if candidate_key:
        headers["X-Aether-First-Admin-Candidate-Key"] = candidate_key
    try:
        status, body = _request(
            "GET",
            f"{base_url}/v1/auth/bootstrap/first-admin",
            headers=headers,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return False, False, f"bootstrap status could not be verified ({type(error).__name__})"
    if status != 200:
        return False, False, f"bootstrap status returned HTTP {status}; no secret was changed"
    try:
        response = json.loads(body or b"{}")
        data = response.get("data", response) if isinstance(response, dict) else None
        claimed = data.get("claimed") if isinstance(data, dict) else None
        candidate_matches = data.get("candidate_matches") if isinstance(data, dict) else None
    except (TypeError, ValueError):
        claimed, candidate_matches = None, None
    if not isinstance(claimed, bool) or not isinstance(candidate_matches, bool):
        return False, False, "bootstrap status response was invalid; no secret was changed"
    return claimed, candidate_matches, ""


def _export_admin_key_for_later_steps(api_key: str) -> tuple[bool, str]:
    """Mask and pass the verified key only to later steps in this job."""
    if not STAGING_ADMIN_KEY_RE.fullmatch(api_key):
        return False, "refusing to export a value that is not a durable staging API key"
    env_path = os.environ.get("GITHUB_ENV", "")
    if not env_path or not os.path.isfile(env_path) or not os.access(env_path, os.W_OK):
        return False, "GITHUB_ENV is unavailable; the key cannot be safely passed to later steps"
    try:
        # Register the runner mask before writing the environment file. The key
        # matches a fixed alphabet, so it cannot inject additional env records.
        print(f"::add-mask::{api_key}", flush=True)
        with open(env_path, "a", encoding="utf-8") as handle:
            handle.write(f"STAGING_ADMIN_API_KEY={api_key}\n")
    except OSError as error:
        return False, f"verified admin key could not be passed to later steps ({type(error).__name__})"
    return True, ""


def _runtime_admin_key(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    existing_key = os.environ.get("EXISTING_STAGING_ADMIN_API_KEY", "").strip()

    env_path = os.environ.get("GITHUB_ENV", "")
    if not env_path or not os.path.isfile(env_path) or not os.access(env_path, os.W_OK):
        print("error: writable GITHUB_ENV is unavailable; no bootstrap request was sent", file=sys.stderr)
        return 2

    reusable_candidate = ""
    if existing_key:
        if STAGING_ADMIN_KEY_RE.fullmatch(existing_key):
            valid, reason, status = _verify_admin_key(base_url, existing_key)
            if valid:
                exported, export_reason = _export_admin_key_for_later_steps(existing_key)
                if not exported:
                    print(f"error: {export_reason}", file=sys.stderr)
                    return 2
                print("existing staging admin credential authenticated; key passed to later steps")
                return 0
            if status not in (401, 403):
                print(f"error: {reason}; refusing to replace or bootstrap", file=sys.stderr)
                return 1
            # A previous attempt may already have persisted this candidate but
            # lost its HTTP response. Reuse it, never mint a second key.
            reusable_candidate = existing_key
        elif not args.allow_bootstrap:
            print("error: configured staging admin key has an invalid shape", file=sys.stderr)
            return 1

    if not args.allow_bootstrap:
        print(
            "error: no verified staging admin key is configured and this lane does not "
            "allow first-admin bootstrap",
            file=sys.stderr,
        )
        return 1
    if not args.confirm_single_use:
        print("error: --confirm-single-use is required; no bootstrap request was sent", file=sys.stderr)
        return 2

    token = os.environ.get("FIRST_ADMIN_BOOTSTRAP_TOKEN", "")
    if len(token.strip()) < 32:
        print("error: FIRST_ADMIN_BOOTSTRAP_TOKEN is unavailable or too short; no request was sent", file=sys.stderr)
        return 2
    if not reusable_candidate and not _gh_token_available():
        print(
            "error: GH_TOKEN must be set to WORKFLOW_DISPATCH_TOKEN or "
            "TF_AMPLIFY_GITHUB_ACCESS_TOKEN; no bootstrap request was sent",
            file=sys.stderr,
        )
        return 2
    claimed, candidate_matches, reason = _bootstrap_marker_state(
        base_url, token, reusable_candidate
    )
    if reason:
        print(f"error: {reason}", file=sys.stderr)
        return 1
    if claimed and not (reusable_candidate and candidate_matches):
        print(
            "error: bootstrap is already claimed by a different or unverifiable key; "
            "refusing to replace the stored admin key",
            file=sys.stderr,
        )
        return 1

    # Reuse a rejected saved candidate only when the durable marker proves it
    # was the key from an interrupted bootstrap. If the marker is unclaimed,
    # the saved value may be stale or belong to another credential path; mint
    # and persist a fresh candidate instead of promoting it to staging admin.
    resume_claimed_request = bool(claimed and reusable_candidate and candidate_matches)
    api_key = reusable_candidate if resume_claimed_request else ("ak_" + secrets.token_hex(12))
    if not resume_claimed_request:
        if not _github_cli_authenticated():
            print(
                "error: configured GitHub token is not authenticated; no secret was changed",
                file=sys.stderr,
            )
            return 2
        if not _store_repository_secret(args.repo, api_key):
            print(
                "error: GitHub secret update failed; the one-time bootstrap was not called",
                file=sys.stderr,
            )
            return 2
        if _repository_secret_exists(args.repo) is not True:
            print(
                "error: GitHub did not confirm STAGING_ADMIN_API_KEY is present; "
                "the one-time bootstrap was not called",
                file=sys.stderr,
            )
            return 2
    else:
        print("bootstrap marker matches the stored key; resuming the identical idempotent request")

    bootstrapped, reason = _request_bootstrap(base_url, token, api_key)
    if not bootstrapped:
        print(f"error: {reason}", file=sys.stderr)
        return 1

    verified, reason, _status = _verify_admin_key(base_url, api_key)
    if not verified:
        print(f"error: saved key could not be verified as admin: {reason}", file=sys.stderr)
        return 1
    exported, reason = _export_admin_key_for_later_steps(api_key)
    if not exported:
        print(f"error: {reason}", file=sys.stderr)
        return 2
    print("first-admin bootstrap completed; saved key authenticated with admin scope")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="HTTPS origin for the staging API")
    parser.add_argument("--repo", required=True, help="GitHub repository in owner/name form")
    parser.add_argument(
        "--preflight-secret-write",
        action="store_true",
        help="prove GitHub repository-secret write access and remove a disposable test secret",
    )
    parser.add_argument(
        "--allow-bootstrap",
        action="store_true",
        help="allow the pilot lane to use the one-time first-admin route if no key authenticates",
    )
    parser.add_argument(
        "--confirm-single-use",
        action="store_true",
        help="explicitly authorize consuming the one-time first-admin bootstrap",
    )
    args = parser.parse_args(argv)

    if not REPOSITORY_RE.fullmatch(args.repo):
        print("error: --repo must be owner/name", file=sys.stderr)
        return 2
    if args.preflight_secret_write:
        if args.base_url or args.allow_bootstrap or args.confirm_single_use:
            parser.error("--preflight-secret-write cannot be combined with bootstrap/runtime options")
        return _preflight_repository_secret_write(args.repo)
    if not args.base_url:
        parser.error("--base-url is required for runtime admin verification")
    errors = _base_url_errors(args.base_url)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 2
    if args.confirm_single_use and not args.allow_bootstrap:
        print("error: --confirm-single-use requires --allow-bootstrap", file=sys.stderr)
        return 2
    return _runtime_admin_key(args)


if __name__ == "__main__":
    raise SystemExit(main())
