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
    secrets = {
        name: (
            "arn:aws:secretsmanager:us-east-1:111122223333:secret:rds!cluster-aether-staging"
            if name == "DATABASE_URL_SECRET"
            else (
                "arn:aws:secretsmanager:us-east-1:111122223333:secret:aether/"
                + checker.SECRET_ENV_TO_CANONICAL_NAME[name]
            )
        )
        for name in secret_names
    }

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
                        "FIRST_ADMIN_BOOTSTRAP_EMAIL": "ops@olympuslabsml.com",
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


def test_pilot_requires_the_first_admin_bootstrap_email():
    original = _client()

    def missing_email(args: list[str]) -> dict[str, Any]:
        payload = original(args)
        if args[:2] == ["ecs", "describe-task-definition"]:
            container = payload["taskDefinition"]["containerDefinitions"][0]
            container["environment"] = [
                item for item in container["environment"]
                if item["name"] != "FIRST_ADMIN_BOOTSTRAP_EMAIL"
            ]
        return payload

    errors = checker.contract_errors(lane="pilot", client=missing_email)
    assert any("first-admin bootstrap email is missing" in error for error in errors)


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


def test_pilot_rejects_a_swapped_stripe_price_mount():
    original = _client()

    def swapped_price(args: list[str]) -> dict[str, Any]:
        payload = original(args)
        if args[:2] == ["ecs", "describe-task-definition"]:
            container = payload["taskDefinition"]["containerDefinitions"][0]
            for mount in container["secrets"]:
                if mount["name"] == "STRIPE_PRICE_ALPHA":
                    mount["valueFrom"] = (
                        "arn:aws:secretsmanager:us-east-1:111122223333:secret:"
                        "aether/stripe-price-beta"
                    )
        return payload

    errors = checker.contract_errors(
        lane="pilot",
        client=swapped_price,
        expected_account_id="111122223333",
    )
    assert any(
        "STRIPE_PRICE_ALPHA" in error and "aether/stripe-price-alpha" in error
        for error in errors
    )


def test_pilot_accepts_exact_six_character_generated_secret_suffix():
    original = _client()

    def generated_suffix(args: list[str]) -> dict[str, Any]:
        payload = original(args)
        if args[:2] == ["ecs", "describe-task-definition"]:
            container = payload["taskDefinition"]["containerDefinitions"][0]
            for mount in container["secrets"]:
                if mount["name"] == "STRIPE_PRICE_ALPHA":
                    mount["valueFrom"] = (
                        "arn:aws:secretsmanager:us-east-1:111122223333:secret:"
                        "aether/stripe-price-alpha-AbCd12"
                    )
        return payload

    assert checker.contract_errors(
        lane="pilot",
        client=generated_suffix,
        expected_account_id="111122223333",
    ) == []


def test_pilot_rejects_a_sibling_secret_with_a_shared_prefix():
    original = _client()

    def sibling_secret(args: list[str]) -> dict[str, Any]:
        payload = original(args)
        if args[:2] == ["ecs", "describe-task-definition"]:
            container = payload["taskDefinition"]["containerDefinitions"][0]
            for mount in container["secrets"]:
                if mount["name"] == "JWT_SECRET":
                    mount["valueFrom"] = (
                        "arn:aws:secretsmanager:us-east-1:111122223333:secret:"
                        "aether/jwt-secret-previous-AbCd12"
                    )
        return payload

    errors = checker.contract_errors(
        lane="pilot",
        client=sibling_secret,
        expected_account_id="111122223333",
    )
    assert any("JWT_SECRET" in error and "aether/jwt-secret" in error for error in errors)


def test_pilot_rejects_secret_mounts_from_wrong_account_or_region():
    original = _client()

    def wrong_location(args: list[str]) -> dict[str, Any]:
        payload = original(args)
        if args[:2] == ["ecs", "describe-task-definition"]:
            container = payload["taskDefinition"]["containerDefinitions"][0]
            for mount in container["secrets"]:
                if mount["name"] == "STRIPE_PRICE_ALPHA":
                    mount["valueFrom"] = (
                        "arn:aws:secretsmanager:eu-west-1:999988887777:secret:"
                        "aether/stripe-price-alpha"
                    )
        return payload

    errors = checker.contract_errors(
        lane="pilot",
        client=wrong_location,
        expected_account_id="111122223333",
    )
    assert any("STRIPE_PRICE_ALPHA" in error and "region" in error for error in errors)
    assert any("STRIPE_PRICE_ALPHA" in error and "account" in error for error in errors)
