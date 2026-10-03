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
WEB = "AETHER-staging-web"
SITE_BEFORE = "AETHER-staging-aether-marketing"
PRODUCT_BEFORE = "AETHER-staging-aether-app"
APP_IDS = {
    WEB: "d-web",
    SITE_BEFORE: "d-aether-marketing",
    PRODUCT_BEFORE: "d-aether-app",
    "AETHER-staging-olympus-marketing": "d-olympus",
    "AETHER-staging-docs": "d-docs",
    "AETHER-staging-status": "d-status",
    "AETHER-production-web": "d-production-status",
}
ALL_HOSTS = ("aether", "www", "docs", "status", "app")


def _client(
    *,
    production_repository: str = checker.REPOSITORY,
    production_commit: str | None = COMMIT,
    domain_branch: str = "main",
    www_branch: str = checker.PRODUCTION_OLYMPUS_BRANCH,
    domain_verified: bool = True,
    domain_dns_record: str | None = None,
    consolidated: bool = True,
    extra_apps: tuple[str, ...] = (),
    web_hosts: tuple[str, ...] = ALL_HOSTS,
):
    """``consolidated`` is the one-app layout (AETHER-staging-web serves every
    host); otherwise the pre-apply layout: the site app (old name) serves
    aether, www, docs and status and the product app serves app.
    ``extra_apps`` are apps that still exist beyond the layout."""
    present = {WEB} if consolidated else {SITE_BEFORE, PRODUCT_BEFORE}
    present |= set(extra_apps)
    present.add("AETHER-production-web")
    hosts_by_app = (
        {"d-web": list(web_hosts)}
        if consolidated
        else {"d-aether-marketing": ["aether", "www", "docs", "status"], "d-aether-app": ["app"]}
    )
    hosts_by_app["d-production-status"] = list(checker.PRODUCTION_HOSTS)
    apps = [
        {
            "name": name,
            "appId": app_id,
            "repository": production_repository if name == "AETHER-production-web" else checker.REPOSITORY,
            "platform": "WEB",
        }
        for name, app_id in APP_IDS.items()
        if name in present
    ]

    def call(args: list[str]) -> dict[str, Any]:
        if args[:2] == ["amplify", "list-apps"]:
            return {"apps": apps}
        if args[:2] == ["amplify", "get-branch"]:
            app_id = args[args.index("--app-id") + 1]
            branch_name = args[args.index("--branch-name") + 1]
            production = app_id == "d-production-status"
            olympus = production and branch_name == checker.PRODUCTION_OLYMPUS_BRANCH
            if branch_name != "main" and not olympus:
                raise RuntimeError("AWS Amplify metadata request failed for amplify")
            return {
                "branch": {
                    "appId": app_id,
                    "branchName": branch_name,
                    "stage": "PRODUCTION" if production else "DEVELOPMENT",
                    "enableAutoBuild": not olympus,
                    "environmentVariables": (
                        checker.PRODUCTION_OLYMPUS_ENVIRONMENT
                        if olympus
                        else checker.PRODUCTION_WEB_ENVIRONMENT
                        if production
                        else {}
                    ),
                }
            }
        if args[:2] == ["amplify", "list-jobs"]:
            app_id = args[args.index("--app-id") + 1]
            commit = production_commit if app_id == "d-production-status" else COMMIT
            return {"jobSummaries": [{"jobId": "10", "status": "SUCCEED", "commitId": commit}]}
        if args[:2] == ["amplify", "get-domain-association"]:
            app_id = args[args.index("--app-id") + 1]
            prefixes = hosts_by_app.get(app_id)
            if not prefixes:
                raise RuntimeError("AWS Amplify metadata request failed for amplify")
            return {
                "domainAssociation": {
                    "domainStatus": "AVAILABLE",
                    "subDomains": [
                        {
                            "subDomainSetting": {
                                "prefix": item,
                                "branchName": (
                                    www_branch
                                    if app_id == "d-production-status" and item == "www"
                                    else domain_branch
                                ),
                            },
                            "verified": domain_verified,
                            **(
                                {"dnsRecord": domain_dns_record}
                                if domain_dns_record is not None
                                else {}
                            ),
                        }
                        for item in prefixes
                    ],
                }
            }
        raise AssertionError(args)

    return call


def test_staging_and_production_status_contracts_accept_exact_metadata():
    client = _client()
    assert checker.contract_errors(mode="staging", expected_commit=COMMIT, client=client) == []
    assert checker.contract_errors(mode="production-status", expected_commit=COMMIT, client=client) == []


def test_staging_contract_waits_for_an_active_reviewed_commit_job():
    base_client = _client()
    statuses = iter(("RUNNING", "SUCCEED"))
    sleeps: list[float] = []

    def client(args: list[str]) -> dict[str, Any]:
        payload = base_client(args)
        if args[:2] == ["amplify", "list-jobs"] and args[args.index("--app-id") + 1] == "d-web":
            payload["jobSummaries"][0]["status"] = next(statuses)
        return payload

    assert checker.contract_errors(
        mode="staging",
        expected_commit=COMMIT,
        wait_for_current_job=True,
        job_timeout_seconds=30,
        job_poll_seconds=5,
        sleeper=sleeps.append,
        client=client,
    ) == []
    assert sleeps == [5]


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


def test_staging_is_one_app_serving_every_host():
    assert checker.STAGING_APPS == (WEB,)
    assert set(checker.STAGING_RUNTIME_ENVIRONMENT) == {WEB}
    assert set(checker.STAGING_HOSTS) == set(ALL_HOSTS)
    for owners in checker.STAGING_HOSTS.values():
        assert owners[0] == WEB


def test_pre_apply_preflight_accepts_the_layout_the_apply_consolidates():
    """The preflight gates the apply that renames the site app and moves the
    app host onto it, so it accepts the site app's old name and the product
    app still serving app; the post-apply check does not."""
    client = _client(consolidated=False)
    assert checker.contract_errors(mode="staging", expected_commit=COMMIT, client=client) == []
    runtime = checker.contract_errors(mode="staging-runtime", expected_commit=COMMIT, client=client)
    assert any(WEB in error for error in runtime)
    assert f"{PRODUCT_BEFORE}: retired staging Amplify app still exists; the unified site serves its hosts" in runtime


def test_staging_rejects_a_host_that_no_app_serves():
    errors = checker.contract_errors(
        mode="staging",
        expected_commit=COMMIT,
        client=_client(web_hosts=("aether", "www", "status", "app")),
    )
    assert errors == [
        f"Amplify app {WEB} staging domain lacks an AVAILABLE docs subdomain on main with a live DNS target"
    ]


def test_retired_apps_fail_only_the_post_apply_check():
    """A retired app that still exists (left behind, or recreated out of band)
    fails the post-apply staging-runtime check, never the pre-apply preflight."""
    client = _client(extra_apps=("AETHER-staging-docs", PRODUCT_BEFORE))
    assert checker.contract_errors(mode="staging", expected_commit=COMMIT, client=client) == []
    assert sorted(checker.contract_errors(mode="staging-runtime", expected_commit=COMMIT, client=client)) == sorted(
        f"{name}: retired staging Amplify app still exists; the unified site serves its hosts"
        for name in ("AETHER-staging-docs", PRODUCT_BEFORE)
    )


def test_staging_runtime_contract_requires_the_site_and_product_settings():
    """The one app builds the site and the product under /app; a branch missing
    their API, status, pricing, cross-site or Auth0 settings builds a broken app."""
    errors = checker.contract_errors(
        mode="staging",
        expected_commit=COMMIT,
        check_runtime_environment=True,
        client=_client(),
    )
    web_errors = [error for error in errors if WEB in error]
    for key in (
        "VITE_API_BASE_URL",
        "VITE_STATUS_API_URL",
        "VITE_STATUS_HISTORY_URL",
        "VITE_PUBLISH_PRICES",
        "VITE_SITE_AETHER_URL",
        "VITE_SITE_OLYMPUS_URL",
        "VITE_AETHER_ENDPOINT",
        "VITE_AUTH0_REDIRECT_URI",
        "VITE_AUTH0_DOMAIN",
    ):
        assert any(key in error for error in web_errors), key


def test_staging_runtime_contract_accepts_exact_branch_origins():
    def client(args: list[str]) -> dict[str, Any]:
        payload = _client()(args)
        if args[:2] == ["amplify", "get-branch"] and args[args.index("--app-id") + 1] == "d-web":
            environment = dict(checker.STAGING_RUNTIME_ENVIRONMENT[WEB])
            environment.update(
                {
                    "VITE_AUTH0_DOMAIN": "tenant.example.auth0.com",
                    "VITE_AUTH0_CLIENT_ID": "client-id",
                    "VITE_AUTH0_AUDIENCE": "https://api.example.com",
                }
            )
            payload["branch"]["environmentVariables"] = environment
        return payload

    assert checker.contract_errors(mode="staging-runtime", expected_commit=COMMIT, check_runtime_environment=True, client=client) == []
    assert checker.STAGING_RUNTIME_ENVIRONMENT[WEB]["VITE_AUTH0_REDIRECT_URI"] == (
        "https://aether.staging.olympuslabsml.com/app/callback"
    )


def test_rejects_invalid_expected_commit_before_aws_calls():
    called = False

    def client(_args: list[str]):
        nonlocal called
        called = True
        raise AssertionError("AWS should not be queried for malformed commit")

    errors = checker.contract_errors(mode="staging", expected_commit="not-a-sha", client=client)
    assert errors == ["expected commit must be a 40-character lowercase Git SHA"]
    assert called is False


def test_production_serves_www_from_the_olympus_site_branch():
    """www is the Olympus Labs build (production-olympus); the other hosts are main."""
    assert checker.PRODUCTION_HOST_BRANCHES == {
        "www": "production-olympus",
        "aether": "main",
        "docs": "main",
        "status": "main",
        "app": "main",
    }
    assert checker.PRODUCTION_OLYMPUS_ENVIRONMENT["VITE_SITE"] == "olympus"
    errors = checker.contract_errors(
        mode="production-status",
        expected_commit=COMMIT,
        client=_client(www_branch="main"),
    )
    assert errors == [
        "Amplify app AETHER-production-web production domain lacks an AVAILABLE www subdomain on production-olympus with a live DNS target"
    ]


def test_production_olympus_branch_must_build_the_olympus_site_from_the_reviewed_commit():
    base = _client()

    def drifted(args: list[str]) -> dict[str, Any]:
        payload = base(args)
        if args[:2] == ["amplify", "get-branch"] and args[args.index("--branch-name") + 1] == "production-olympus":
            payload["branch"]["environmentVariables"] = checker.PRODUCTION_WEB_ENVIRONMENT
            payload["branch"]["enableAutoBuild"] = True
        if args[:2] == ["amplify", "list-jobs"] and args[args.index("--branch-name") + 1] == "production-olympus":
            payload["jobSummaries"][0]["commitId"] = "b" * 40
        return payload

    errors = checker.contract_errors(mode="production-status", expected_commit=COMMIT, client=drifted)
    assert any("production-olympus branch has VITE_SITE=None" in e for e in errors)
    assert any("production-olympus branch must not auto-build" in e for e in errors)
    assert any("latest production-olympus job is not for the reviewed commit" in e for e in errors)
    assert not any(" main " in e for e in errors)


def test_production_requires_the_olympus_site_branch():
    base = _client()

    def missing(args: list[str]) -> dict[str, Any]:
        if args[:2] == ["amplify", "get-branch"] and args[args.index("--branch-name") + 1] == "production-olympus":
            raise RuntimeError("AWS Amplify metadata request failed for amplify")
        return base(args)

    errors = checker.contract_errors(mode="production-status", expected_commit=COMMIT, client=missing)
    assert "Amplify app AETHER-production-web has no production-olympus branch" in errors
