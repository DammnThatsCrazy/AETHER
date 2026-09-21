#!/usr/bin/env python3
"""Verify the live ECS task definitions match the selected staging lane.

This is a metadata-only check. It reads service/task-definition shape and
secret *names* from ECS, never secret values. The pilot gate is intentionally
stricter than a source-text check: it proves the registered revisions have the
four self-service Stripe price mounts and do not still carry the deferred Kyber
Google mounts from an older full-lane revision.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from typing import Any, NoReturn


AwsCall = Callable[[list[str]], Mapping[str, Any]]

SECRET_ENV_TO_CANONICAL_NAME = {
    "JWT_SECRET": "jwt-secret",
    "BYOK_ENCRYPTION_KEY": "byok-encryption-key",
    "STRIPE_SECRET_KEY": "stripe-secret-key",
    "STRIPE_WEBHOOK_SECRET": "stripe-webhook-secret",
    "ORACLE_SIGNER_PRIVATE_KEY": "oracle-signer-private-key",
    "WATERMARK_SECRET_KEY": "watermark-secret-key",
    "CANARY_SECRET_SEED": "canary-secret-seed",
    "EXTRACTION_CANARY_SEED": "extraction-canary-seed",
    "SDK_CONFIG_SECRET": "sdk-config-secret",
    "FIRST_ADMIN_BOOTSTRAP_TOKEN": "first-admin-bootstrap-token",
    "JWT_SECRET_PREVIOUS": "jwt-secret-previous",
    "BYOK_ENCRYPTION_KEY_PREVIOUS": "byok-encryption-key-previous",
    "STRIPE_PRICE_ALPHA": "stripe-price-alpha",
    "STRIPE_PRICE_BETA": "stripe-price-beta",
    "STRIPE_PRICE_GAMMA": "stripe-price-gamma",
    "STRIPE_PRICE_DELTA": "stripe-price-delta",
    "KYBER_GOOGLE_CLIENT_ID": "kyber-google-client-id",
    "KYBER_GOOGLE_CLIENT_SECRET": "kyber-google-client-secret",
    "REDIS_PASSWORD": "redis-auth-token",
}
SECRET_ARN_RE = re.compile(
    r"^arn:aws:secretsmanager:(?P<region>[^:]+):(?P<account>\d{12}):secret:(?P<resource>[^:]+)(?::.*)?$"
)
DATABASE_SECRET_RESOURCE_PREFIX = "rds!cluster-"

SERVICES = {
    "AETHER-staging-backend": "api",
    "AETHER-staging-lean-worker": "lean-worker",
}

COMMON_SECRET_ENV = frozenset(
    {
        "JWT_SECRET",
        "BYOK_ENCRYPTION_KEY",
        "DATABASE_URL_SECRET",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "ORACLE_SIGNER_PRIVATE_KEY",
        "WATERMARK_SECRET_KEY",
        "CANARY_SECRET_SEED",
        "EXTRACTION_CANARY_SEED",
        "SDK_CONFIG_SECRET",
        "FIRST_ADMIN_BOOTSTRAP_TOKEN",
        "JWT_SECRET_PREVIOUS",
        "BYOK_ENCRYPTION_KEY_PREVIOUS",
    }
)
PILOT_PRICE_SECRET_ENV = frozenset(
    {"STRIPE_PRICE_ALPHA", "STRIPE_PRICE_BETA", "STRIPE_PRICE_GAMMA", "STRIPE_PRICE_DELTA"}
)
KYBER_SECRET_ENV = frozenset({"KYBER_GOOGLE_CLIENT_ID", "KYBER_GOOGLE_CLIENT_SECRET"})
KYBER_ONLY_ENV = frozenset(
    {
        "KYBER_ALLOWED_ORIGINS",
        "KYBER_GOOGLE_HOSTED_DOMAIN",
        "KYBER_GOOGLE_REDIRECT_URI",
        "KYBER_WEBAUTHN_RP_ID",
        "KYBER_WEBAUTHN_ORIGIN",
    }
)
REQUIRED_ENV = {
    "APP_ENV": "staging",
    "AETHER_ENV": "staging",
    "DEPLOYMENT_PROFILE": "staging",
    "CREDENTIAL_CIPHER": "aws_kms",
    "EVENT_BROKER": "sns_sqs",
    "CACHE_BACKEND": "dynamodb",
    "GRAPH_BACKEND": "postgres",
    "ML_SERVING_INLINE": "true",
    "POLICY_ENFORCEMENT_ENABLED": "true",
    "ROUTE_REGISTRY_ENFORCED": "true",
    "KYBER_OPERATOR_GATE_ENFORCED": "true",
}
PILOT_ENV = {
    "DEPLOYMENT_LANE": "pilot",
    "STRIPE_BILLING_ENABLED": "true",
    "KYBER_WORKFORCE_IDENTITY_ENABLED": "false",
    "KYBER_DEVICE_TRUST_REQUIRED": "false",
    "KYBER_BACKEND_AUTHZ_ENFORCED": "false",
    "KYBER_SCOPE_V2_ENABLED": "false",
    "KYBER_STEP_UP_REQUIRED": "false",
    "KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED": "false",
    "KYBER_BOOTSTRAP_ENABLED": "false",
    "KYBER_SESSION_COOKIE_SECURE": "true",
}
FULL_ENV = {
    "DEPLOYMENT_LANE": "full",
    "STRIPE_BILLING_ENABLED": "false",
    "KYBER_WORKFORCE_IDENTITY_ENABLED": "true",
    "KYBER_DEVICE_TRUST_REQUIRED": "true",
    "KYBER_BACKEND_AUTHZ_ENFORCED": "true",
    "KYBER_SCOPE_V2_ENABLED": "true",
    "KYBER_STEP_UP_REQUIRED": "true",
    "KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED": "false",
    "KYBER_BOOTSTRAP_ENABLED": "false",
    "KYBER_SESSION_COOKIE_SECURE": "true",
}


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def aws_json(args: list[str]) -> Mapping[str, Any]:
    result = subprocess.run(
        ["aws", *args, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown AWS error"
        fail(f"AWS metadata request failed for {args[0]}: {detail}")
    try:
        payload = json.loads(result.stdout or "{}")
    except ValueError as exc:
        fail(f"AWS metadata request for {args[0]} was not JSON: {exc}")
    if not isinstance(payload, Mapping):
        fail(f"AWS metadata request for {args[0]} returned a non-object")
    return payload


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _env_map(container: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in container.get("environment") or []:
        item = _mapping(raw)
        name = item.get("name")
        value = item.get("value")
        if isinstance(name, str) and isinstance(value, str):
            result[name] = value
    return result


def _secret_map(container: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in container.get("secrets") or []:
        item = _mapping(raw)
        name = item.get("name")
        value_from = item.get("valueFrom")
        if isinstance(name, str) and isinstance(value_from, str):
            result[name] = value_from
    return result


def _secret_mount_errors(
    *,
    service: str,
    env_name: str,
    value_from: str,
    expected_account_id: str | None,
) -> list[str]:
    """Validate the complete ARN identity for one ECS secret mount.

    Secrets Manager app ARNs include a generated suffix after the canonical
    name. The suffix is accepted, but the environment variable must still map
    to its own reviewed name; a valid-looking ARN for a sibling secret is not
    sufficient. Aurora's managed master secret is the one deliberate
    exception: Terraform exposes it as DATABASE_URL_SECRET and AWS names it
    with the rds!cluster- resource prefix rather than aether/.
    """
    errors: list[str] = []
    match = SECRET_ARN_RE.fullmatch(value_from)
    if match is None:
        return [f"{service}: secret mount {env_name} is not a complete Secrets Manager ARN"]

    region = match.group("region")
    account = match.group("account")
    resource = match.group("resource")
    if region != "us-east-1":
        errors.append(f"{service}: secret mount {env_name} is in region {region!r}, expected 'us-east-1'")
    if expected_account_id is not None and account != expected_account_id:
        errors.append(
            f"{service}: secret mount {env_name} is in account {account!r}, expected {expected_account_id!r}"
        )

    if env_name == "DATABASE_URL_SECRET":
        if not resource.startswith(DATABASE_SECRET_RESOURCE_PREFIX):
            errors.append(
                f"{service}: secret mount {env_name} must reference the Aurora-managed "
                f"{DATABASE_SECRET_RESOURCE_PREFIX}* secret"
            )
        return errors

    canonical_name = SECRET_ENV_TO_CANONICAL_NAME.get(env_name)
    if canonical_name is None:
        return [f"{service}: secret mount {env_name} is not in the reviewed ECS secret mapping"]
    expected_resource = f"aether/{canonical_name}"
    if resource != expected_resource and not resource.startswith(f"{expected_resource}-"):
        errors.append(
            f"{service}: secret mount {env_name} must reference {expected_resource} "
            "(with an optional Secrets Manager suffix)"
        )
    return errors


def contract_errors(
    *,
    lane: str,
    client: AwsCall,
    cluster: str = "AETHER-staging",
    expected_account_id: str | None = None,
) -> list[str]:
    if lane not in {"pilot", "full"}:
        return [f"deployment lane must be pilot or full, got {lane!r}"]

    errors: list[str] = []
    expected_env = dict(REQUIRED_ENV)
    expected_env.update(PILOT_ENV if lane == "pilot" else FULL_ENV)
    expected_secret_names = COMMON_SECRET_ENV | (PILOT_PRICE_SECRET_ENV if lane == "pilot" else KYBER_SECRET_ENV)

    for service, expected_role in SERVICES.items():
        payload = client(["ecs", "describe-services", "--cluster", cluster, "--services", service])
        services = payload.get("services")
        failures = payload.get("failures")
        if isinstance(failures, list) and failures:
            errors.append(f"{service}: ECS describe-services returned a failure")
            continue
        if not isinstance(services, list) or len(services) != 1:
            errors.append(f"{service}: expected exactly one ECS service")
            continue
        service_payload = _mapping(services[0])
        task_definition = service_payload.get("taskDefinition")
        if not isinstance(task_definition, str) or not task_definition:
            errors.append(f"{service}: has no task definition")
            continue

        definition_payload = client(["ecs", "describe-task-definition", "--task-definition", task_definition])
        definition = _mapping(definition_payload.get("taskDefinition"))
        containers = definition.get("containerDefinitions")
        if not isinstance(containers, list):
            errors.append(f"{service}: task definition has no container definitions")
            continue
        expected_container_name = "aether-backend" if expected_role == "api" else "lean-worker"
        matching = [
            _mapping(container)
            for container in containers
            if _mapping(container).get("name") == expected_container_name
        ]
        if len(matching) != 1:
            errors.append(f"{service}: expected one {expected_container_name} container")
            continue
        container = matching[0]
        environment = _env_map(container)
        secrets = _secret_map(container)

        for name, expected in expected_env.items():
            if environment.get(name) != expected:
                errors.append(f"{service}: {name}={environment.get(name)!r}, expected {expected!r}")
        if environment.get("AETHER_ROLE") != expected_role:
            errors.append(f"{service}: AETHER_ROLE is not {expected_role!r}")
        for name in ("CREDENTIAL_KMS_KEY_ID", "SQS_QUEUE_URL", "SQS_DLQ_QUEUE_URL"):
            if not environment.get(name, "").strip():
                errors.append(f"{service}: required non-empty runtime variable {name} is missing")
        if lane == "pilot":
            for name in ("STRIPE_CHECKOUT_SUCCESS_URL", "STRIPE_CHECKOUT_CANCEL_URL", "STRIPE_PORTAL_RETURN_URL"):
                if not environment.get(name, "").startswith("https://app.staging.olympuslabsml.com/"):
                    errors.append(f"{service}: {name} is not a staging HTTPS billing URL")

        missing = sorted(expected_secret_names - secrets.keys())
        if missing:
            errors.append(f"{service}: missing ECS secret mounts: {', '.join(missing)}")
        for name, value_from in secrets.items():
            errors.extend(
                _secret_mount_errors(
                    service=service,
                    env_name=name,
                    value_from=value_from,
                    expected_account_id=expected_account_id,
                )
            )
        if lane == "pilot":
            forbidden = sorted((KYBER_SECRET_ENV | KYBER_ONLY_ENV) & (secrets.keys() | environment.keys()))
            if forbidden:
                errors.append(f"{service}: pilot task still carries deferred Kyber runtime fields: {', '.join(forbidden)}")
        else:
            missing_kyber = sorted(KYBER_ONLY_ENV - environment.keys())
            if missing_kyber:
                errors.append(f"{service}: full task is missing Kyber runtime fields: {', '.join(missing_kyber)}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=("pilot", "full"), required=True)
    parser.add_argument("--cluster", default="AETHER-staging")
    args = parser.parse_args(argv)
    identity = aws_json(["sts", "get-caller-identity"])
    expected_account_id = identity.get("Account")
    if not isinstance(expected_account_id, str) or not re.fullmatch(r"\d{12}", expected_account_id):
        fail("AWS caller identity did not provide a valid 12-digit account ID")
    errors = contract_errors(
        lane=args.lane,
        cluster=args.cluster,
        client=aws_json,
        expected_account_id=expected_account_id,
    )
    if errors:
        print("staging ECS task-definition contract FAILED:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"staging ECS task-definition contract valid: lane={args.lane}; secret values were not read")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
