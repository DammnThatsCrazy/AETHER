#!/usr/bin/env python3
"""Verify Amplify app ownership, branch stage, domain, and artifact provenance.

This is a metadata-only check. It never reads a repository token, build
artifact, or application secret. It makes the two Amplify surfaces that are
otherwise easy to miss explicit:

* all five customer-facing staging apps must be connected to this repository,
  use ``main`` as a development branch, and have a successful job for the
  reviewed commit; and
* the separate public status app must be connected to this repository, keep its
  ``main`` branch in ``PRODUCTION`` stage, have a successful job for the same
  reviewed commit, and expose a live custom-domain CNAME.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from typing import Any, NoReturn


REPOSITORY = "https://github.com/DammnThatsCrazy/AETHER"
STAGING_DOMAIN = "staging.olympuslabsml.com"
PRODUCTION_DOMAIN = "olympuslabsml.com"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

STAGING_RUNTIME_ENVIRONMENT: dict[str, dict[str, str]] = {
    "AETHER-staging-olympus-marketing": {
        "AETHER_ENV": "staging",
    },
    "AETHER-staging-aether-marketing": {
        "AETHER_ENV": "staging",
    },
    "AETHER-staging-docs": {
        "AETHER_ENV": "staging",
    },
    "AETHER-staging-aether-app": {
        "AETHER_ENV": "staging",
        "VITE_AETHER_ENV": "staging",
        "VITE_API_BASE_URL": "https://api.staging.olympuslabsml.com",
        "VITE_AETHER_ENDPOINT": "https://api.staging.olympuslabsml.com",
        "VITE_AUTH0_REDIRECT_URI": "https://app.staging.olympuslabsml.com/callback",
        "VITE_AUTH0_LOGOUT_URI": "https://app.staging.olympuslabsml.com/login",
    },
    "AETHER-staging-status": {
        "AETHER_ENV": "staging",
        "VITE_STATUS_API_URL": "https://api.staging.olympuslabsml.com/health",
        "VITE_STATUS_DOCS_URL": "https://docs.staging.olympuslabsml.com",
        "VITE_STATUS_AETHER_MARKETING_URL": "https://aether.staging.olympuslabsml.com",
    },
}
STAGING_REQUIRED_RUNTIME_KEYS: dict[str, tuple[str, ...]] = {
    "AETHER-staging-aether-app": (
        "VITE_AUTH0_DOMAIN",
        "VITE_AUTH0_CLIENT_ID",
        "VITE_AUTH0_AUDIENCE",
    ),
}

STAGING_APPS: dict[str, str] = {
    "AETHER-staging-olympus-marketing": "www",
    "AETHER-staging-aether-marketing": "aether",
    "AETHER-staging-docs": "docs",
    "AETHER-staging-aether-app": "app",
    "AETHER-staging-status": "status",
}
STATUS_APP = "aether-status"
PRODUCTION_STATUS_ENVIRONMENT = {
    "AETHER_ENV": "production",
    "VITE_STATUS_API_URL": "https://api.olympuslabsml.com/health",
    "VITE_STATUS_DOCS_URL": "https://docs.olympuslabsml.com",
    "VITE_STATUS_AETHER_MARKETING_URL": "https://aether.olympuslabsml.com",
}
Runner = Callable[..., subprocess.CompletedProcess[str]]
AwsCall = Callable[[list[str]], Mapping[str, Any]]
DnsResolver = Callable[[str], str]


def fail(message: str) -> NoReturn:
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def aws_json(args: list[str], *, runner: Runner = subprocess.run) -> Mapping[str, Any]:
    result = runner(["aws", *args, "--output", "json"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"AWS Amplify metadata request failed for {args[0]}")
    try:
        payload = __import__("json").loads(result.stdout or "{}")
    except ValueError as exc:
        raise RuntimeError("AWS Amplify metadata response was not JSON") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("AWS Amplify metadata response was not an object")
    return payload


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _repository_identity(value: Any) -> str:
    """Compare GitHub repository URLs without treating harmless API casing as drift."""
    if not isinstance(value, str):
        return ""
    normalized = value.strip().rstrip("/")
    if normalized.casefold().endswith(".git"):
        normalized = normalized[:-4]
    return normalized.casefold()


def _public_cname(hostname: str) -> str:
    """Return the public CNAME target without reading any application data."""
    result = subprocess.run(
        ["dig", "+short", "CNAME", hostname],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    for line in result.stdout.splitlines():
        value = line.strip().rstrip(".").lower()
        if value:
            return value
    return ""


def _apps_by_name(client: AwsCall) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    payload = client(["amplify", "list-apps", "--max-results", "100"])
    apps = payload.get("apps")
    if not isinstance(apps, list):
        return {}, ["Amplify list-apps returned no app list"]
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for raw in apps:
        app = _mapping(raw)
        name = app.get("name")
        if isinstance(name, str):
            grouped.setdefault(name, []).append(app)
    errors: list[str] = []
    result: dict[str, Mapping[str, Any]] = {}
    for name, matches in grouped.items():
        if len(matches) == 1:
            result[name] = matches[0]
        else:
            errors.append(f"Amplify app name {name} is not unique")
    return result, errors


def _latest_job(
    app_id: str,
    branch_name: str,
    client: AwsCall,
) -> tuple[Mapping[str, Any] | None, list[str]]:
    payload = client(
        [
            "amplify",
            "list-jobs",
            "--app-id",
            app_id,
            "--branch-name",
            branch_name,
            "--max-results",
            "10",
        ]
    )
    jobs = payload.get("jobSummaries")
    if not isinstance(jobs, list) or not jobs:
        return None, [f"Amplify app {app_id} branch {branch_name} has no job history"]
    normalized = [_mapping(job) for job in jobs]
    normalized = [job for job in normalized if job]
    if not normalized:
        return None, [f"Amplify app {app_id} branch {branch_name} has no readable job history"]

    def job_number(job: Mapping[str, Any]) -> int:
        try:
            return int(str(job.get("jobId", "0")))
        except ValueError:
            return 0

    return max(normalized, key=job_number), []


def _check_app(
    *,
    name: str,
    app: Mapping[str, Any] | None,
    branch_stage: str,
    expected_commit: str | None,
    subdomain_prefix: str | None,
    expected_branch_environment: Mapping[str, str] | None = None,
    required_branch_environment_keys: tuple[str, ...] = (),
    check_job_provenance: bool = True,
    check_domain: bool = True,
    domain_name: str | None = None,
    dns_resolver: DnsResolver = _public_cname,
    client: AwsCall,
) -> list[str]:
    errors: list[str] = []
    if app is None:
        return [f"required Amplify app {name} is missing"]
    app_id = app.get("appId")
    if not isinstance(app_id, str) or not app_id:
        return [f"Amplify app {name} has no appId"]
    if _repository_identity(app.get("repository")) != _repository_identity(REPOSITORY):
        errors.append(f"Amplify app {name} is not connected to the reviewed repository")
    if app.get("platform") != "WEB":
        errors.append(f"Amplify app {name} is not a WEB app")
    branch_payload = client(["amplify", "get-branch", "--app-id", app_id, "--branch-name", "main"])
    branch = _mapping(branch_payload.get("branch"))
    if branch.get("branchName") != "main":
        errors.append(f"Amplify app {name} has no canonical main branch")
    if branch.get("stage") != branch_stage:
        errors.append(f"Amplify app {name} main branch is {branch.get('stage')!r}, expected {branch_stage}")
    if branch.get("enableAutoBuild") is not True:
        errors.append(f"Amplify app {name} main branch does not have auto-build enabled")
    if expected_branch_environment is not None:
        environment = _mapping(branch.get("environmentVariables"))
        for key, expected in expected_branch_environment.items():
            if environment.get(key) != expected:
                errors.append(
                    f"Amplify app {name} main branch has {key}={environment.get(key)!r}, expected the reviewed production value"
                )
        for key in required_branch_environment_keys:
            value = environment.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"Amplify app {name} main branch is missing non-empty {key}")
    if check_job_provenance:
        job, job_errors = _latest_job(app_id, "main", client)
        errors.extend(f"Amplify app {name}: {error}" for error in job_errors)
        if job is not None:
            if job.get("status") != "SUCCEED":
                errors.append(f"Amplify app {name} latest main job is {job.get('status')!r}, not SUCCEED")
            if expected_commit is not None and job.get("commitId") != expected_commit:
                errors.append(f"Amplify app {name} latest main job is not for the reviewed commit")

    if check_domain and subdomain_prefix is not None:
        requested_domain = domain_name or STAGING_DOMAIN
        domain_label = "staging" if requested_domain == STAGING_DOMAIN else "production"
        association_payload = client(
            [
                "amplify",
                "get-domain-association",
                "--app-id",
                app_id,
                "--domain-name",
                requested_domain,
            ]
        )
        association = _mapping(association_payload.get("domainAssociation"))
        if association.get("domainStatus") != "AVAILABLE":
            errors.append(
                f"Amplify app {name} {domain_label} domain association is not AVAILABLE"
            )
        subdomains = association.get("subDomains")
        matching = [
            _mapping(item)
            for item in subdomains
            if isinstance(item, Mapping)
            and _mapping(item.get("subDomainSetting")).get("prefix") == subdomain_prefix
            and _mapping(item.get("subDomainSetting")).get("branchName") == "main"
        ] if isinstance(subdomains, list) else []
        live_dns = False
        if matching and matching[0].get("verified") is not True:
            dns_record = matching[0].get("dnsRecord")
            expected_target = (
                str(dns_record).rsplit(" ", 1)[-1].rstrip(".").lower()
                if isinstance(dns_record, str) and dns_record.strip()
                else ""
            )
            live_dns = bool(
                expected_target
                and dns_resolver(f"{subdomain_prefix}.{requested_domain}") == expected_target
            )
        if not matching or (matching[0].get("verified") is not True and not live_dns):
            errors.append(
                f"Amplify app {name} {domain_label} domain lacks an AVAILABLE {subdomain_prefix} subdomain with a live DNS target"
            )
    return errors


def contract_errors(
    *,
    mode: str,
    expected_commit: str | None = None,
    check_runtime_environment: bool = False,
    dns_resolver: DnsResolver = _public_cname,
    client: AwsCall,
) -> list[str]:
    errors: list[str] = []
    if expected_commit is not None and not COMMIT_RE.fullmatch(expected_commit):
        errors.append("expected commit must be a 40-character lowercase Git SHA")
        return errors
    apps, app_errors = _apps_by_name(client)
    errors.extend(app_errors)
    if mode in ("staging", "staging-runtime"):
        runtime_only = mode == "staging-runtime"
        for name, prefix in STAGING_APPS.items():
            errors.extend(
                _check_app(
                    name=name,
                    app=apps.get(name),
                    branch_stage="DEVELOPMENT",
                    expected_commit=expected_commit,
                    subdomain_prefix=prefix,
                    expected_branch_environment=(
                        STAGING_RUNTIME_ENVIRONMENT[name]
                        if check_runtime_environment
                        else None
                    ),
                    required_branch_environment_keys=(
                        STAGING_REQUIRED_RUNTIME_KEYS.get(name, ())
                        if check_runtime_environment
                        else ()
                    ),
                    check_job_provenance=not runtime_only,
                    check_domain=not runtime_only,
                    client=client,
                    dns_resolver=dns_resolver,
                )
            )
    elif mode == "production-status":
        errors.extend(
            _check_app(
                name=STATUS_APP,
                app=apps.get(STATUS_APP),
                branch_stage="PRODUCTION",
                expected_commit=expected_commit,
                subdomain_prefix="status",
                expected_branch_environment=PRODUCTION_STATUS_ENVIRONMENT,
                domain_name=PRODUCTION_DOMAIN,
                client=client,
                dns_resolver=dns_resolver,
            )
        )
    else:
        errors.append(f"unsupported Amplify contract mode {mode}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("staging", "staging-runtime", "production-status"), required=True)
    parser.add_argument("--expected-commit", help="Require the latest successful job to use this commit")
    parser.add_argument(
        "--check-runtime-environment",
        action="store_true",
        help="Require the reviewed staging branch runtime links (never reads secrets)",
    )
    args = parser.parse_args(argv)
    try:
        errors = contract_errors(
            mode=args.mode,
            expected_commit=args.expected_commit,
            check_runtime_environment=args.check_runtime_environment or args.mode == "staging-runtime",
            client=lambda request: aws_json(request),
        )
    except RuntimeError as exc:
        print(f"staging Amplify contract FAILED: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("staging Amplify contract FAILED:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Amplify {args.mode} contract valid for {args.expected_commit or 'the current deployed job'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
