"""Staging runs the full public journey: self sign-up and lead email.

Staging is where the sign-up → tenant → plan → checkout journey and the
contact/pilot notifications are exercised before production, so its profile
must turn both on and the ECS module must pass them to the tasks explicitly
(the backend's own default disables self sign-up on staging).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TF = ROOT / "deploy/aws/terraform"


def _tfvars(name: str) -> dict[str, str]:
    text = (TF / "profiles" / f"{name}.tfvars").read_text(encoding="utf-8")
    return dict(re.findall(r"^([a-z_]+)\s*=\s*(\S+)", text, re.MULTILINE))


def test_staging_profile_enables_self_signup_and_email() -> None:
    staging = _tfvars("staging")
    assert staging.get("self_signup_enabled") == "true"
    assert staging.get("email_enabled") == "true"


def test_ecs_tasks_receive_explicit_signup_and_email_settings() -> None:
    ecs = (TF / "modules/ecs/main.tf").read_text(encoding="utf-8")
    assert (
        '{ name = "SSO_SELF_SIGNUP_ENABLED", value = var.self_signup_enabled ? "true" : "false" }'
        in ecs
    )
    assert '{ name = "EMAIL_FROM_ADDRESS", value = "noreply@${var.email_sender_domain}" }' in ecs
    assert '{ name = "LEAD_NOTIFICATION_EMAIL", value = var.lead_notification_email }' in ecs
    # The SES client targets the region whose identity the task role may use.
    assert '{ name = "EMAIL_AWS_REGION", value = data.aws_region.current.name }' in ecs
    # Both service families (backend and runtime workers) carry the settings.
    assert ecs.count("local.self_signup_runtime_environment,") == 2
    assert ecs.count("local.email_runtime_environment,") == 2


def test_task_role_sends_only_from_the_sender_domain() -> None:
    ecs = (TF / "modules/ecs/main.tf").read_text(encoding="utf-8")
    start = ecs.index("ses_statements = var.email_enabled ? [")
    block = ecs[start : ecs.index("] : []", start)]
    # The email adapter calls SendEmail only (config/credential_contracts.yaml
    # email_ses scope); raw MIME sending is not granted.
    assert 'Action   = ["ses:SendEmail"]' in block
    assert "SendRawEmail" not in block
    assert "identity/${var.email_sender_domain}" in block
    assert '"*"' not in block


def test_self_signup_defaults_follow_the_backend_outside_staging() -> None:
    """Unset keeps self sign-up on for production and off for other staging lanes."""
    main = (TF / "main.tf").read_text(encoding="utf-8")
    assert (
        'self_signup_enabled = var.self_signup_enabled != null ? var.self_signup_enabled : var.environment != "staging"'
        in main
    )
    assert "self_signup_enabled         = local.self_signup_enabled" in main
    for profile in ("production", "production-lean"):
        path = TF / "profiles" / f"{profile}.tfvars"
        if path.exists():
            assert _tfvars(profile).get("self_signup_enabled") in (None, "true")


def test_staging_release_manifest_resolves_email_on() -> None:
    manifest = yaml.safe_load(
        (ROOT / "config/release/feature_flags/staging.yaml").read_text(encoding="utf-8")
    )
    flags = manifest["runtime"]["flags"]
    assert "EMAIL_ENABLED" in flags["on"]
    assert "EMAIL_ENABLED" not in flags.get("off", [])


def test_release_manifests_resolve_every_deploy_default_on_flag() -> None:
    """SSO_SELF_SIGNUP_ENABLED and EMAIL_ENABLED are resolved explicitly."""
    result = subprocess.run(
        [sys.executable, "scripts/release/check_resolved_feature_flags.py", "--all"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ("staging", "production-lean"):
        flags = yaml.safe_load(
            (ROOT / f"config/release/feature_flags/{name}.yaml").read_text(encoding="utf-8")
        )["runtime"]["flags"]
        assert "SSO_SELF_SIGNUP_ENABLED" in flags["on"]
