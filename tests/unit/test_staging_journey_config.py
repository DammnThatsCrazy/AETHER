"""Staging runs the full public journey: self sign-up and lead email.

Staging is where the sign-up → tenant → plan → checkout journey and the
contact/pilot notifications are exercised before production, so its profile
must turn both on and the ECS module must pass them to the tasks explicitly
(the backend's own default disables self sign-up on staging).
"""

from __future__ import annotations

import re
from pathlib import Path

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
    assert '{ name = "SSO_SELF_SIGNUP_ENABLED", value = var.self_signup_enabled ? "true" : "false" }' in ecs
    assert '{ name = "EMAIL_FROM_ADDRESS", value = "noreply@${var.email_sender_domain}" }' in ecs
    assert '{ name = "LEAD_NOTIFICATION_EMAIL", value = var.lead_notification_email }' in ecs
    # Both service families (backend and runtime workers) carry the settings.
    assert ecs.count("local.self_signup_runtime_environment,") == 2
    assert ecs.count("local.email_runtime_environment,") == 2


def test_task_role_sends_only_from_the_sender_domain() -> None:
    ecs = (TF / "modules/ecs/main.tf").read_text(encoding="utf-8")
    start = ecs.index("ses_statements = var.email_enabled ? [")
    block = ecs[start:ecs.index("] : []", start)]
    assert 'Action   = ["ses:SendEmail", "ses:SendRawEmail"]' in block
    assert "identity/${var.email_sender_domain}" in block
    assert '"*"' not in block
