"""Tests for the metadata-only Amplify provenance contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/check_amplify_app_contract.py"
SPEC = importlib.util.spec_from_file_location("amplify_app_contract", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

COMMIT = "a" * 40
APP_IDS = {
    "AETHER-staging-olympus-marketing": "d-olympus",
    "AETHER-staging-aether-marketing": "d-aether-marketing",
    "AETHER-staging-docs": "d-docs",
    "AETHER-staging-aether-app": "d-aether-app",
    "AETHER-staging-status": "d-status",
    "aether-status": "d-production-status",
}


def _client(
    *,
    production_repository: str = checker.REPOSITORY,
    production_commit: str | None = COMMIT,
    domain_branch: str = "main",
    domain_verified: bool = True,
    domain_dns_record: str | None = None,
):
    apps = []
    for name, app_id in APP_IDS.items():
        apps.append(
            {
                "name": name,
                "appId": app_id,
                "repository": production_repository if name == "aether-status" else checker.REPOSITORY,
                "platform": "WEB",
            }
        )

    def call(args: list[str]) -> dict[str, Any]:
        if args[:2] == ["amplify", "list-apps"]:
            return {"apps": apps}
        if args[:2] == ["amplify", "get-branch"]:
            app_id = args[args.index("--app-id") + 1]
            return {
                "branch": {
                    "appId": app_id,
                    "branchName": "main",
                    "stage": "PRODUCTION" if app_id == "d-production-status" else "DEVELOPMENT",
                    "enableAutoBuild": True,
                    "environmentVariables": (
                        checker.PRODUCTION_STATUS_ENVIRONMENT
                        if app_id == "d-production-status"
                        else {}
                    ),
                }
            }
        if args[:2] == ["amplify", "list-jobs"]:
            app_id = args[args.index("--app-id") + 1]
            commit = production_commit if app_id == "d-production-status" else COMMIT
            return {"jobSummaries": [{"jobId": "10", "status": "SUCCEED", "commitId": commit}]}
        if args[:2] == ["amplify", "get-domain-association"]:
            prefix = {
                "d-olympus": "www",
                "d-aether-marketing": "aether",
                "d-docs": "docs",
                "d-aether-app": "app",
                "d-status": "status",
                "d-production-status": "status",
            }[args[args.index("--app-id") + 1]]
            return {
                "domainAssociation": {
                    "domainStatus": "AVAILABLE",
                    "subDomains": [
                        {
                            "subDomainSetting": {"prefix": prefix, "branchName": domain_branch},
                            "verified": domain_verified,
                            **(
                                {"dnsRecord": domain_dns_record}
                                if domain_dns_record is not None
                                else {}
                            ),
                        }
                    ],
                }
            }
        raise AssertionError(args)

    return call


def test_staging_and_production_status_contracts_accept_exact_metadata():
    client = _client()
    assert checker.contract_errors(mode="staging", expected_commit=COMMIT, client=client) == []
    assert checker.contract_errors(mode="production-status", expected_commit=COMMIT, client=client) == []


def test_repository_contract_accepts_amplify_github_url_casing_and_git_suffix():
    client = _client(production_repository="https://github.com/dammnthatscrazy/aether.git/")
    assert checker.contract_errors(mode="production-status", expected_commit=COMMIT, client=client) == []


def test_production_status_rejects_manual_or_stale_provenance():
    errors = checker.contract_errors(
        mode="production-status",
        expected_commit=COMMIT,
        client=_client(production_repository=None, production_commit=None),
    )
    assert any("not connected" in error for error in errors)
    assert any("not for the reviewed commit" in error for error in errors)


def test_production_status_rejects_missing_runtime_links():
    client = _client()
    original = client

    def missing_runtime_links(args: list[str]) -> dict[str, Any]:
        payload = original(args)
        if args[:2] == ["amplify", "get-branch"] and args[args.index("--app-id") + 1] == "d-production-status":
            payload["branch"]["environmentVariables"] = {"AETHER_ENV": "production"}
        return payload

    errors = checker.contract_errors(
        mode="production-status",
        expected_commit=COMMIT,
        client=missing_runtime_links,
    )
    assert any("VITE_STATUS_API_URL" in error for error in errors)


def test_production_status_requires_the_canonical_status_hostname_mapping():
    errors = checker.contract_errors(
        mode="production-status",
        expected_commit=COMMIT,
        client=_client(domain_branch="preview"),
    )
    assert any("production domain lacks an AVAILABLE status subdomain" in error for error in errors)


def test_production_status_accepts_live_dns_when_legacy_verified_bit_is_stale():
    errors = checker.contract_errors(
        mode="production-status",
        expected_commit=COMMIT,
        client=_client(
            domain_verified=False,
            domain_dns_record="status CNAME d1589n0luhr9u1.cloudfront.net",
        ),
        dns_resolver=lambda hostname: "d1589n0luhr9u1.cloudfront.net",
    )
    assert errors == []


def test_staging_domain_requires_the_main_branch_mapping():
    errors = checker.contract_errors(
        mode="staging",
        expected_commit=COMMIT,
        client=_client(domain_branch="preview"),
    )
    assert any("staging domain lacks an AVAILABLE" in error for error in errors)


def test_staging_runtime_contract_requires_api_and_custom_status_origins():
    client = _client()
    errors = checker.contract_errors(
        mode="staging",
        expected_commit=COMMIT,
        check_runtime_environment=True,
        client=client,
    )
    assert any("VITE_STATUS_API_URL" in error for error in errors)
    assert any("VITE_STATUS_DOCS_URL" in error for error in errors)
    assert any("VITE_STATUS_AETHER_MARKETING_URL" in error for error in errors)


def test_staging_runtime_contract_accepts_exact_branch_origins():
    def client(args: list[str]) -> dict[str, Any]:
        payload = _client()(args)
        if args[:2] == ["amplify", "get-branch"]:
            app_id = args[args.index("--app-id") + 1]
            name = next(name for name, value in APP_IDS.items() if value == app_id)
            environment = dict(checker.STAGING_RUNTIME_ENVIRONMENT[name])
            if name == "AETHER-staging-aether-app":
                environment.update(
                    {
                        "VITE_AUTH0_DOMAIN": "tenant.example.auth0.com",
                        "VITE_AUTH0_CLIENT_ID": "client-id",
                        "VITE_AUTH0_AUDIENCE": "https://api.example.com",
                    }
                )
            payload["branch"]["environmentVariables"] = environment
        return payload

    assert checker.contract_errors(
        mode="staging-runtime",
        expected_commit=COMMIT,
        client=client,
    ) == []


def test_rejects_invalid_expected_commit_before_aws_calls():
    called = False

    def client(_args: list[str]):
        nonlocal called
        called = True
        raise AssertionError("AWS should not be queried for malformed commit")

    errors = checker.contract_errors(mode="staging", expected_commit="not-a-sha", client=client)
    assert errors == ["expected commit must be a 40-character lowercase Git SHA"]
    assert called is False
