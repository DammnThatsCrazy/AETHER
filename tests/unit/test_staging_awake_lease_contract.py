from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/check_staging_awake_lease.py"
SPEC = importlib.util.spec_from_file_location("staging_awake_lease", SCRIPT)
assert SPEC and SPEC.loader
lease_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lease_module)


def _lease(*, since: datetime, until: datetime, extensions: int = 0) -> str:
    import json

    return json.dumps({
        "awake_since": since.isoformat(),
        "awake_until": until.isoformat(),
        "extensions": extensions,
    })


def test_awake_lease_accepts_current_unextended_four_hour_window():
    now = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
    assert lease_module.lease_errors(
        _lease(since=now - timedelta(hours=1), until=now + timedelta(hours=3)), now
    ) == []


def test_awake_lease_rejects_expiry_malformed_extension_and_ttl_overrun():
    now = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
    expired = _lease(since=now - timedelta(hours=1), until=now - timedelta(seconds=1))
    assert "staging awake lease has expired" in lease_module.lease_errors(expired, now)

    too_long = _lease(since=now - timedelta(hours=1), until=now + timedelta(hours=8))
    assert "staging awake lease exceeds its per-lease TTL" in lease_module.lease_errors(too_long, now)

    invalid_count = _lease(since=now, until=now + timedelta(hours=1), extensions=True)
    assert "staging awake lease has an invalid extension count" in lease_module.lease_errors(
        invalid_count, now
    )
    assert lease_module.lease_errors("not-json", now) == [
        "staging awake lease is missing or malformed"
    ]


def test_static_publication_revalidates_staging_lease_before_each_write():
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text())
    publish = next(
        step for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name") == "Publish private static SPA origins"
    )
    run = publish["run"]
    for command in (
        'aws s3 sync "dist-$app"',
        'aws s3 cp "dist-$app/index.html"',
    ):
        position = run.index(command)
        assert "assert_awake_lease" in run[:position]
    assert run.count("assert_awake_lease") == 3  # function declaration + two write guards
    assert "check_staging_awake_lease.py" in run


def test_rehearsal_delivery_contracts_and_live_role_checks_block_wake_plan():
    workflow = yaml.safe_load((ROOT / ".github/workflows/staging-lifecycle.yml").read_text())
    preflight = workflow["jobs"]["preflight-rehearsal-inputs"]
    assert preflight["environment"] == "staging"
    assert preflight["permissions"]["id-token"] == "write"
    steps = preflight["steps"]
    scripts = "\n".join(step.get("run", "") for step in steps)
    assert "--purpose delivery" in scripts
    assert "--purpose rehearsal" in scripts
    assert "--preflight-secret-write" in scripts
    assert "simulate-principal-policy" in scripts
    assert "check_staging_task_definition_contract.py" in scripts
    assert "AetherStagingDeploy" in scripts

    plan = workflow["jobs"]["wake-plan"]
    assert "preflight-rehearsal-inputs" in plan["needs"]
    assert "needs.preflight-rehearsal-inputs.result == 'success'" in plan["if"]
    apply = workflow["jobs"]["wake-apply"]
    assert "needs.preflight-rehearsal-inputs.result == 'success'" in apply["if"]
