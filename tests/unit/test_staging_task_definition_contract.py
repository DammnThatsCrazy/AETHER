"""Tests for the live ECS staging lane contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/check_staging_task_definition_contract.py"
SPEC = importlib.util.spec_from_file_location("staging_task_definition_contract", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def _client(*, pilot: bool = True):
    secret_names = checker.COMMON_SECRET_ENV | (
        checker.PILOT_PRICE_SECRET_ENV if pilot else checker.KYBER_SECRET_ENV
    )
    secrets = {name: f"arn:aws:secretsmanager:us-east-1:111122223333:secret:aether/{name}" for name in secret_names}

    def call(args: list[str]) -> dict[str, Any]:
        if args[:2] == ["ecs", "describe-services"]:
            service = args[-1]
            role = "api" if service.endswith("backend") else "lean-worker"
            return {"services": [{"taskDefinition": f"arn:task-definition/staging-{role}:7"}], "failures": []}
        if args[:2] == ["ecs", "describe-task-definition"]:
            role = "api" if "-api:" in args[-1] else "lean-worker"
            environment = dict(checker.REQUIRED_ENV)
            environment.update(checker.PILOT_ENV if pilot else checker.FULL_ENV)
            environment["AETHER_ROLE"] = role
            environment.update(
                {
                    "CREDENTIAL_KMS_KEY_ID": "arn:aws:kms:us-east-1:111122223333:key/example",
                    "SQS_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/111122223333/aether",
                    "SQS_DLQ_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/111122223333/aether-dlq",
                }
            )
            if pilot:
                environment.update(
                    {
                        "STRIPE_CHECKOUT_SUCCESS_URL": "https://app.staging.olympuslabsml.com/billing/success",
                        "STRIPE_CHECKOUT_CANCEL_URL": "https://app.staging.olympuslabsml.com/billing/cancel",
                        "STRIPE_PORTAL_RETURN_URL": "https://app.staging.olympuslabsml.com/billing",
                    }
                )
            else:
                environment.update({name: "configured" for name in checker.KYBER_ONLY_ENV})
            return {
                "taskDefinition": {
                    "containerDefinitions": [
                        {"name": "aether-backend" if role == "api" else "lean-worker", "environment": [{"name": k, "value": v} for k, v in environment.items()], "secrets": [{"name": k, "valueFrom": v} for k, v in secrets.items()]}
                    ]
                }
            }
        raise AssertionError(args)

    return call


def test_pilot_accepts_exact_customer_facing_task_shape():
    assert checker.contract_errors(lane="pilot", client=_client()) == []


def test_full_accepts_exact_workforce_task_shape():
    assert checker.contract_errors(lane="full", client=_client(pilot=False)) == []


def test_pilot_rejects_old_full_lane_mounts():
    client = _client()
    original = client

    def old_definition(args: list[str]) -> dict[str, Any]:
        payload = original(args)
        if args[:2] == ["ecs", "describe-task-definition"]:
            container = payload["taskDefinition"]["containerDefinitions"][0]
            container["secrets"] = [
                {"name": name, "valueFrom": f"arn:aws:secretsmanager:us-east-1:111122223333:secret:aether/{name}"}
                for name in checker.COMMON_SECRET_ENV | checker.KYBER_SECRET_ENV
            ]
            container["environment"].extend(
                [{"name": name, "value": "true"} for name in checker.KYBER_ONLY_ENV]
            )
        return payload

    errors = checker.contract_errors(lane="pilot", client=old_definition)
    assert any("missing ECS secret mounts" in error for error in errors)
    assert any("deferred Kyber runtime fields" in error for error in errors)
