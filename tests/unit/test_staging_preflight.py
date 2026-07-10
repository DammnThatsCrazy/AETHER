"""Tests for the staging preflight gate (scripts/staging_preflight.py).

Hermetic where it matters: the Settings() subprocess and the contract-gate
subprocesses are monkeypatched except in the one test that deliberately
proves the real config.settings.Settings() constructs under the valid
fixture environment (settings.py is stdlib-only, so that subprocess needs
no backend deps).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import staging_preflight
from scripts.lib import preflight_contracts, preflight_db, preflight_env
from scripts.lib import preflight_http, preflight_redis
from scripts.lib.preflight_results import (
    FAIL,
    PASS,
    SKIP,
    CheckResult,
    all_passed,
    count_by_status,
    failed,
    passed,
    skipped,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "staging_preflight"
VALID_FIXTURE = FIXTURES / "valid.env"
INVALID_FIXTURE = FIXTURES / "invalid.env"


def _stub_settings_ok(env, **kwargs):
    return True, "stub: Settings() constructed"


def _by_suffix(results, prefix):
    return {r.name.removeprefix(f"{prefix}:"): r for r in results}


# ---------------------------------------------------------------------------
# Env file parsing
# ---------------------------------------------------------------------------


def test_parse_env_file_ignores_comments_blanks_and_quotes(tmp_path):
    env_file = tmp_path / "candidate.env"
    env_file.write_text(
        "# a comment\n"
        "\n"
        "AETHER_ENV=staging\n"
        "export JWT_SECRET=abc123\n"
        "  QUOTED='hello world'  \n"
        'DQUOTED="v=1"\n'
        "not a kv line\n"
        "EMPTY=\n",
        encoding="utf-8",
    )
    env = preflight_env.parse_env_file(env_file)
    assert env == {
        "AETHER_ENV": "staging",
        "JWT_SECRET": "abc123",
        "QUOTED": "hello world",
        "DQUOTED": "v=1",
        "EMPTY": "",
    }


def test_load_candidate_env_defaults_to_process_env(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_SENTINEL_VAR", "sentinel")
    env = preflight_env.load_candidate_env(None)
    assert env["PREFLIGHT_SENTINEL_VAR"] == "sentinel"


# ---------------------------------------------------------------------------
# Env checks — valid fixture
# ---------------------------------------------------------------------------


def test_valid_fixture_passes_all_env_checks(monkeypatch):
    monkeypatch.setattr(preflight_env, "run_settings_subprocess", _stub_settings_ok)
    env = preflight_env.parse_env_file(VALID_FIXTURE)
    results = preflight_env.run_env_checks(env)
    assert all(r.status == PASS for r in results), [
        (r.name, r.detail) for r in results if r.status != PASS
    ]
    assert [r.name for r in results] == [
        "env:aether-env",
        "env:inmemory-store-disabled",
        "env:cors-origins",
        "env:database-url",
        "env:redis-config",
        "env:signing-secrets",
        "env:no-placeholder-secrets",
        "env:settings-construct",
    ]


def test_valid_fixture_settings_subprocess_genuinely_constructs():
    """Real subprocess: config.settings.Settings() must accept valid.env.

    settings.py is stdlib-only, so this runs even before backend deps
    finish installing.
    """
    env = preflight_env.parse_env_file(VALID_FIXTURE)
    ok, detail = preflight_env.run_settings_subprocess(env)
    assert ok, f"Settings() rejected the valid fixture: {detail}"


# ---------------------------------------------------------------------------
# Env checks — invalid fixture fails with specific reasons
# ---------------------------------------------------------------------------


def test_invalid_fixture_fails_with_specific_reasons(monkeypatch):
    monkeypatch.setattr(preflight_env, "run_settings_subprocess", _stub_settings_ok)
    env = preflight_env.parse_env_file(INVALID_FIXTURE)
    results = preflight_env.run_env_checks(env)
    by_suffix = _by_suffix(results, "env")

    assert by_suffix["aether-env"].status == FAIL
    assert "local" in by_suffix["aether-env"].detail

    assert by_suffix["no-placeholder-secrets"].status == FAIL
    assert "JWT_SECRET" in by_suffix["no-placeholder-secrets"].detail
    assert "changeme" in by_suffix["no-placeholder-secrets"].detail

    assert by_suffix["cors-origins"].status == FAIL
    assert "*" in by_suffix["cors-origins"].detail

    assert by_suffix["database-url"].status == FAIL

    assert by_suffix["inmemory-store-disabled"].status == FAIL
    assert "AETHER_ALLOW_INMEMORY_STORE" in by_suffix["inmemory-store-disabled"].detail

    # Every failure carries a remediation.
    for r in results:
        if r.status == FAIL:
            assert r.remediation, f"{r.name} has no remediation"


def test_cors_check_rejects_localhost_and_unset(monkeypatch):
    monkeypatch.setattr(preflight_env, "run_settings_subprocess", _stub_settings_ok)
    base = preflight_env.parse_env_file(VALID_FIXTURE)

    localhost_env = dict(base, CORS_ORIGINS="https://a.io,http://localhost:3000")
    by_suffix = _by_suffix(preflight_env.run_env_checks(localhost_env), "env")
    assert by_suffix["cors-origins"].status == FAIL
    assert "localhost" in by_suffix["cors-origins"].detail

    unset_env = dict(base)
    del unset_env["CORS_ORIGINS"]
    by_suffix = _by_suffix(preflight_env.run_env_checks(unset_env), "env")
    assert by_suffix["cors-origins"].status == FAIL
    assert "localhost" in by_suffix["cors-origins"].detail  # names the default fallback


@pytest.mark.parametrize("placeholder", preflight_env.PLACEHOLDER_SUBSTRINGS)
def test_every_placeholder_substring_is_detected(monkeypatch, placeholder):
    monkeypatch.setattr(preflight_env, "run_settings_subprocess", _stub_settings_ok)
    env = dict(preflight_env.parse_env_file(VALID_FIXTURE))
    env["WATERMARK_SECRET_KEY"] = f"prefix-{placeholder.upper()}-suffix"
    by_suffix = _by_suffix(preflight_env.run_env_checks(env), "env")
    assert by_suffix["no-placeholder-secrets"].status == FAIL
    assert "WATERMARK_SECRET_KEY" in by_suffix["no-placeholder-secrets"].detail


def test_missing_signing_secret_fails(monkeypatch):
    monkeypatch.setattr(preflight_env, "run_settings_subprocess", _stub_settings_ok)
    env = dict(preflight_env.parse_env_file(VALID_FIXTURE))
    del env["SDK_CONFIG_SECRET"]
    by_suffix = _by_suffix(preflight_env.run_env_checks(env), "env")
    assert by_suffix["signing-secrets"].status == FAIL
    assert "SDK_CONFIG_SECRET" in by_suffix["signing-secrets"].detail


def test_production_requires_byok_encryption_key(monkeypatch):
    monkeypatch.setattr(preflight_env, "run_settings_subprocess", _stub_settings_ok)
    env = dict(preflight_env.parse_env_file(VALID_FIXTURE))
    env["AETHER_ENV"] = "production"
    del env["BYOK_ENCRYPTION_KEY"]
    by_suffix = _by_suffix(preflight_env.run_env_checks(env), "env")
    assert by_suffix["signing-secrets"].status == FAIL
    assert "BYOK_ENCRYPTION_KEY" in by_suffix["signing-secrets"].detail


def test_settings_subprocess_failure_detail_is_surfaced(monkeypatch):
    monkeypatch.setattr(
        preflight_env,
        "run_settings_subprocess",
        lambda env, **kw: (False, "RuntimeError: JWT_SECRET must be set in non-local environments."),
    )
    env = preflight_env.parse_env_file(VALID_FIXTURE)
    by_suffix = _by_suffix(preflight_env.run_env_checks(env), "env")
    assert by_suffix["settings-construct"].status == FAIL
    assert "JWT_SECRET" in by_suffix["settings-construct"].detail


# ---------------------------------------------------------------------------
# DB / Redis / HTTP checks — skip semantics and fail-closed inputs
# ---------------------------------------------------------------------------


async def test_db_checks_skip_in_dry_run():
    results = await preflight_db.run_db_checks({}, dry_run=True)
    assert [r.name for r in results] == list(preflight_db.CHECK_NAMES)
    assert all(r.status == SKIP for r in results)


async def test_db_checks_fail_without_database_url():
    results = await preflight_db.run_db_checks({}, dry_run=False)
    assert all(r.status == FAIL for r in results)
    assert "DATABASE_URL" in results[0].detail


def test_dsn_normalization():
    assert (
        preflight_db.normalize_dsn("postgresql+asyncpg://u:p@h:5432/d")
        == "postgresql://u:p@h:5432/d"
    )
    assert preflight_db.normalize_dsn("asyncpg://u:p@h/d") == "postgresql://u:p@h/d"
    assert preflight_db.normalize_dsn("postgresql://u:p@h/d") == "postgresql://u:p@h/d"


async def test_redis_check_skips_in_dry_run():
    results = await preflight_redis.run_redis_checks({}, dry_run=True)
    assert [r.status for r in results] == [SKIP]


async def test_redis_check_fails_without_config():
    results = await preflight_redis.run_redis_checks({}, dry_run=False)
    assert [r.status for r in results] == [FAIL]


def test_redis_url_resolution():
    assert preflight_redis.resolve_redis_url({"REDIS_URL": "redis://r:6379/1"}) == "redis://r:6379/1"
    assert (
        preflight_redis.resolve_redis_url({"REDIS_HOST": "r.internal"})
        == "redis://r.internal:6379/0"
    )
    assert (
        preflight_redis.resolve_redis_url(
            {"REDIS_HOST": "r", "REDIS_PORT": "7000", "REDIS_DB": "2", "REDIS_PASSWORD": "pw"}
        )
        == "redis://:pw@r:7000/2"
    )
    assert preflight_redis.resolve_redis_url({}) == ""


async def test_http_checks_skip_without_base_url():
    results = await preflight_http.run_http_checks(None, dry_run=False)
    assert [r.name for r in results] == list(preflight_http.CHECK_NAMES)
    assert all(r.status == SKIP for r in results)


async def test_http_checks_skip_in_dry_run():
    results = await preflight_http.run_http_checks("https://api.example.test", dry_run=True)
    assert all(r.status == SKIP for r in results)


def test_health_result_flags_failing_dependencies():
    result = preflight_http._health_result(
        200,
        {
            "status": "degraded",
            "dependencies": {"redis": {"status": "error"}, "db": {"status": "ok"}},
        },
    )
    assert result.status == FAIL
    assert "redis" in result.detail

    result = preflight_http._health_result(
        200, {"status": "healthy", "dependencies": {"db": {"status": "ok"}}}
    )
    assert result.status == PASS


# ---------------------------------------------------------------------------
# Contracts checks
# ---------------------------------------------------------------------------


def test_missing_parallel_wave_scripts_fail_live_and_skip_in_dry_run(tmp_path):
    # A bare root without the parallel-wave scripts; stub bump_version so the
    # always-run version-alignment check has something real to execute.
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "bump_version.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8"
    )

    live = {r.name: r for r in preflight_contracts.run_contract_checks(dry_run=False, root=tmp_path)}
    assert live["contracts:sdk-contracts"].status == FAIL
    assert "script missing" in live["contracts:sdk-contracts"].detail
    assert live["contracts:version-consistency"].status == FAIL
    assert live["contracts:version-alignment"].status == PASS

    dry = {r.name: r for r in preflight_contracts.run_contract_checks(dry_run=True, root=tmp_path)}
    assert dry["contracts:sdk-contracts"].status == SKIP
    assert "WARNING" in dry["contracts:sdk-contracts"].detail
    assert dry["contracts:version-consistency"].status == SKIP


def test_contract_check_failure_surfaces_output_tail(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "validate_sdk_contracts.py").write_text(
        "import sys\nprint('drift in sdk surface')\nsys.exit(1)\n", encoding="utf-8"
    )
    (scripts_dir / "check_version_consistency.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8"
    )
    (scripts_dir / "bump_version.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8"
    )
    results = {r.name: r for r in preflight_contracts.run_contract_checks(dry_run=False, root=tmp_path)}
    assert results["contracts:sdk-contracts"].status == FAIL
    assert "drift in sdk surface" in results["contracts:sdk-contracts"].detail
    assert results["contracts:version-consistency"].status == PASS


# ---------------------------------------------------------------------------
# Aggregation + fail-closed self-test
# ---------------------------------------------------------------------------


def test_all_passed_and_counts():
    results = [passed("a"), skipped("b", "why"), failed("c", "boom", "fix c")]
    assert not all_passed(results)
    assert all_passed([passed("a"), skipped("b")])
    assert count_by_status(results) == {PASS: 1, FAIL: 1, SKIP: 1}


def test_check_result_rejects_unknown_status():
    with pytest.raises(ValueError):
        CheckResult(name="x", status="MAYBE")


def test_build_report_aggregation():
    report = staging_preflight.build_report([passed("a"), skipped("b")])
    assert report["passed"] is True
    assert report["dry_run"] is False
    assert "invalid_fixture_checks" not in report

    report = staging_preflight.build_report(
        [passed("a"), failed("b", "boom")],
        invalid_fixture_checks=[failed("env:invalid-fixture:aether-env")],
        dry_run=True,
    )
    assert report["passed"] is False
    assert report["dry_run"] is True
    assert len(report["invalid_fixture_checks"]) == 1


def test_self_test_passes_when_invalid_fixture_fails_closed():
    prefix = staging_preflight.INVALID_PREFIX
    invalid_results = [
        failed(f"{prefix}:{suffix}", "expected failure")
        for suffix in staging_preflight.EXPECTED_INVALID_FAILURES
    ]
    result = staging_preflight.evaluate_fail_closed_self_test(invalid_results)
    assert result.status == PASS


def test_self_test_detects_gate_regression():
    prefix = staging_preflight.INVALID_PREFIX
    # Gate regression: the invalid fixture suddenly passes cors-origins.
    invalid_results = [
        failed(f"{prefix}:aether-env"),
        passed(f"{prefix}:cors-origins"),
        failed(f"{prefix}:database-url"),
        failed(f"{prefix}:no-placeholder-secrets"),
    ]
    result = staging_preflight.evaluate_fail_closed_self_test(invalid_results)
    assert result.status == FAIL
    assert "cors-origins" in result.detail


# ---------------------------------------------------------------------------
# run_preflight / JSON shape / exit codes
# ---------------------------------------------------------------------------


def _stub_contract_checks(**kwargs):
    return [
        skipped("contracts:sdk-contracts", "stub"),
        skipped("contracts:version-consistency", "stub"),
        passed("contracts:version-alignment", "stub"),
    ]


def test_dry_run_report_shape_and_pass(monkeypatch):
    monkeypatch.setattr(preflight_env, "run_settings_subprocess", _stub_settings_ok)
    monkeypatch.setattr(preflight_contracts, "run_contract_checks", _stub_contract_checks)

    report = staging_preflight.run_preflight(dry_run=True)

    assert set(report) == {"dry_run", "passed", "checks", "invalid_fixture_checks"}
    assert report["dry_run"] is True
    assert report["passed"] is True, [
        c for c in report["checks"] if c["status"] == "FAIL"
    ]
    for check in report["checks"] + report["invalid_fixture_checks"]:
        assert set(check) == {"name", "status", "detail", "remediation"}
        assert check["status"] in {"PASS", "FAIL", "SKIP"}

    names = [c["name"] for c in report["checks"]]
    # Valid fixture env checks, self-test, service skips, contract checks.
    assert "env:valid-fixture:aether-env" in names
    assert staging_preflight.SELF_TEST_NAME in names
    assert "db:connect" in names and "redis:ping" in names and "http:health" in names
    statuses = {c["name"]: c["status"] for c in report["checks"]}
    assert statuses["db:connect"] == "SKIP"
    assert statuses["redis:ping"] == "SKIP"
    assert statuses["http:ready"] == "SKIP"
    assert statuses[staging_preflight.SELF_TEST_NAME] == "PASS"
    # The report is JSON-serializable.
    json.dumps(report)


def test_run_preflight_with_env_file_fails_on_bad_env(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight_env, "run_settings_subprocess", _stub_settings_ok)
    monkeypatch.setattr(preflight_contracts, "run_contract_checks", _stub_contract_checks)
    env_file = tmp_path / "bad.env"
    env_file.write_text("AETHER_ENV=dev\nCORS_ORIGINS=*\n", encoding="utf-8")

    report = staging_preflight.run_preflight(env_file=str(env_file))

    assert report["dry_run"] is False
    assert report["passed"] is False
    statuses = {c["name"]: c["status"] for c in report["checks"]}
    assert statuses["env:aether-env"] == "FAIL"
    assert statuses["env:cors-origins"] == "FAIL"
    assert statuses["env:database-url"] == "FAIL"
    # No DATABASE_URL => db checks fail closed rather than silently skipping.
    assert statuses["db:connect"] == "FAIL"


def test_main_exit_codes_and_json_output(monkeypatch, capsys):
    monkeypatch.setattr(
        staging_preflight,
        "run_preflight",
        lambda **kw: {"dry_run": False, "passed": True, "checks": []},
    )
    assert staging_preflight.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True

    monkeypatch.setattr(
        staging_preflight,
        "run_preflight",
        lambda **kw: {
            "dry_run": False,
            "passed": False,
            "checks": [failed("env:aether-env", "boom", "fix it").to_dict()],
        },
    )
    assert staging_preflight.main([]) == 1
    out = capsys.readouterr().out
    assert "RESULT: FAIL" in out
    assert "Required fix: fix it" in out


def test_cli_rejects_dry_run_with_live_flags():
    with pytest.raises(SystemExit):
        staging_preflight.parse_args(["--dry-run", "--base-url", "https://x.test"])
    with pytest.raises(SystemExit):
        staging_preflight.parse_args(["--dry-run", "--env-file", "whatever.env"])
    with pytest.raises(SystemExit):
        staging_preflight.parse_args(["--env-file", "does-not-exist.env"])
