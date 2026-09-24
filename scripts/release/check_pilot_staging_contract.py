#!/usr/bin/env python3
"""Fail-closed, credential-free contract for the lean AWS staging lane.

The pilot lane is a complete Aether staging deployment on AWS.  It is not a
second Terraform profile and it is not a demo path: the canonical ``staging``
state, Terraform promotion authority, immutable delivery workflow, lifecycle
workflow, and smoke workflow remain authoritative.  Only Kyber workforce
identity and GCP/Google-hosted credentials are intentionally deferred.

This checker deliberately does not contact AWS and never accepts secret values
as arguments.  It proves the repository-side wiring is present before a pilot
workflow is allowed to dispatch the mutating authorities.  The live workflow
has a separate preflight for the real Stripe test price secrets.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKFLOW = ROOT / ".github/workflows/pilot-staging.yml"
LANE_TOKEN = "deployment_lane"
LANES = ("full", "pilot")
PILOT = "pilot"
CANONICAL_PROFILE = "staging"

AUTHORITY_WORKFLOWS = (
    ".github/workflows/terraform-promote.yml",
    ".github/workflows/deploy.yml",
    ".github/workflows/staging-lifecycle.yml",
    ".github/workflows/staging-smoke.yml",
)

STRIPE_ENVIRONMENT = (
    "STRIPE_BILLING_ENABLED",
    "STRIPE_PRICE_ALPHA",
    "STRIPE_PRICE_BETA",
    "STRIPE_PRICE_GAMMA",
    "STRIPE_PRICE_DELTA",
    "STRIPE_CHECKOUT_SUCCESS_URL",
    "STRIPE_CHECKOUT_CANCEL_URL",
    "STRIPE_PORTAL_RETURN_URL",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
)
STRIPE_SECRET_NAMES = (
    "stripe-secret-key",
    "stripe-webhook-secret",
    "stripe-price-alpha",
    "stripe-price-beta",
    "stripe-price-gamma",
    "stripe-price-delta",
    "stripe-price-epsilon",
    "stripe-price-omicron",
    "stripe-price-omega",
)
STRIPE_REQUIRED_RUNTIME_SECRET_NAMES = (
    "stripe-secret-key",
    "stripe-webhook-secret",
    "stripe-price-alpha",
    "stripe-price-beta",
    "stripe-price-gamma",
    "stripe-price-delta",
)
# These are intentionally repository-side surface checks.  They keep the
# contract explicit without pretending that static text proves an AWS apply.
REQUIRED_SURFACES: tuple[tuple[str, tuple[Path, ...], tuple[str, ...]], ...] = (
    (
        "AWS networking",
        (ROOT / "deploy/aws/terraform/main.tf",),
        ('module "vpc"',),
    ),
    (
        "durable Aurora database",
        (ROOT / "deploy/aws/terraform/main.tf",),
        ('module "aurora"',),
    ),
    (
        "AWS Secrets Manager",
        (ROOT / "deploy/aws/terraform/main.tf", ROOT / "deploy/aws/terraform/modules/secrets/main.tf"),
        ('module "secrets"',),
    ),
    (
        "ECS backend runtime",
        (ROOT / "deploy/aws/terraform/main.tf", ROOT / "deploy/aws/terraform/modules/ecs/main.tf"),
        ('module "ecs"',),
    ),
    (
        "ALB/HTTPS ingress",
        (ROOT / "deploy/aws/terraform/main.tf", ROOT / "deploy/aws/terraform/modules/alb/main.tf"),
        ("aws_lb_listener", "https"),
    ),
    (
        "Aether customer-facing static surface",
        (ROOT / "deploy/aws/terraform/main.tf", ROOT / ".github/workflows/deploy.yml"),
        ("aws_amplify_app", "aether-spa"),
    ),
    (
        "tenant isolation",
        (ROOT / ".github/workflows/staging-lifecycle.yml", ROOT / "scripts/staging_capability_matrix.py"),
        ("tenant", "isolation"),
    ),
    (
        "observability",
        (ROOT / "deploy/aws/terraform/main.tf", ROOT / ".github/workflows/staging-lifecycle.yml"),
        ("cloudwatch", "metrics"),
    ),
    (
        "migration/readiness",
        (ROOT / ".github/workflows/deploy.yml", ROOT / ".github/workflows/staging-lifecycle.yml"),
        ("alembic", "/v1/ready"),
    ),
    (
        "lifecycle/redeploy/rollback controls",
        (ROOT / ".github/workflows/staging-lifecycle.yml", ROOT / ".github/workflows/deploy.yml"),
        ("rollback", "services-stable"),
    ),
    (
        "Aether smoke coverage",
        (ROOT / ".github/workflows/staging-smoke.yml", ROOT / "package.json"),
        ("smoke:staging",),
    ),
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read {path.relative_to(ROOT)}: {exc}") from exc


def _workflow_on(document: dict[str, Any]) -> Any:
    # PyYAML's YAML 1.1 loader parses the bare GitHub key ``on`` as True.
    return document.get("on", document.get(True))


def _workflow_inputs(document: dict[str, Any]) -> dict[str, Any]:
    triggers = _workflow_on(document)
    if not isinstance(triggers, dict):
        return {}
    dispatch = triggers.get("workflow_dispatch") or {}
    if not isinstance(dispatch, dict):
        return {}
    inputs = dispatch.get("inputs") or {}
    return inputs if isinstance(inputs, dict) else {}


def _combined(paths: tuple[Path, ...]) -> str:
    return "\n".join(_read(path) for path in paths if path.exists())


def _missing_all(text: str, tokens: tuple[str, ...]) -> list[str]:
    return [token for token in tokens if token not in text]


def _active_profile_errors(workflow_text: str) -> list[str]:
    errors: list[str] = []
    if not re.search(r"(?:profile|PROFILE)\s*[=:'\"]+\s*staging\b", workflow_text):
        errors.append("pilot path must dispatch the canonical profile staging")
    if re.search(r"(?:profile|PROFILE)\s*[=:'\"]+\s*(?:pilot|staging-pilot)\b", workflow_text):
        errors.append("pilot path must not invent a pilot or staging-pilot Terraform profile")
    return errors


def find_errors(workflow_path: Path = DEFAULT_WORKFLOW, lane: str = PILOT) -> list[str]:
    """Return actionable contract failures without contacting AWS."""

    errors: list[str] = []
    if lane not in LANES:
        errors.append(f"{LANE_TOKEN} must be one of full, pilot; received {lane!r}")
    if lane != PILOT:
        errors.append("pilot-staging.yml only accepts deployment_lane=pilot")

    if not workflow_path.exists():
        return errors + [f"pilot workflow is missing: {workflow_path.relative_to(ROOT)}"]

    workflow_text = _read(workflow_path)
    try:
        document = yaml.safe_load(workflow_text) or {}
    except yaml.YAMLError as exc:
        return errors + [f"pilot workflow is not valid YAML: {exc}"]
    if not isinstance(document, dict):
        return errors + ["pilot workflow YAML root must be a mapping"]

    triggers = _workflow_on(document)
    trigger_keys = set(triggers) if isinstance(triggers, dict) else set()
    if trigger_keys != {"workflow_dispatch"}:
        errors.append(
            "pilot workflow must be dispatch-only; found triggers "
            + ", ".join(sorted(str(key) for key in trigger_keys))
        )
    inputs = _workflow_inputs(document)
    lane_input = inputs.get(LANE_TOKEN)
    if not isinstance(lane_input, dict):
        errors.append(f"pilot workflow is missing the {LANE_TOKEN} choice input")
    else:
        options = lane_input.get("options") or lane_input.get("choices") or []
        if set(options) != set(LANES):
            errors.append(f"{LANE_TOKEN} input must offer exactly full and pilot")
        if lane_input.get("default") != PILOT:
            errors.append(f"pilot workflow {LANE_TOKEN} input must default to pilot")

    errors.extend(_active_profile_errors(workflow_text))
    for authority in AUTHORITY_WORKFLOWS:
        if authority not in workflow_text:
            errors.append(f"pilot path does not reference canonical authority {authority}")

    # A pilot plan is not allowed to create a saved plan against remote price
    # secrets that are not yet Terraform-owned. The entry point and lifecycle
    # workflow must dispatch the confirmation-gated, import-only reconciler
    # before every pilot planning path; the promotion workflow separately
    # refuses a plan whose state is still incomplete.
    lifecycle_text = _read(ROOT / ".github/workflows/staging-lifecycle.yml")
    promote_text = _read(ROOT / ".github/workflows/terraform-promote.yml")
    for label, text, tokens in (
        (
            "pilot state reconciliation",
            workflow_text,
            (
                "staging-state-reconcile.yml",
                "staging_secret_names=",
                "staging_secrets_kms_key_arn",
                "IMPORT-STAGING",
            ),
        ),
        (
            "lifecycle pilot state reconciliation",
            lifecycle_text,
            (
                "staging-state-reconcile.yml",
                "staging_secret_names=",
                "staging_secrets_kms_key_arn",
                "IMPORT-STAGING",
            ),
        ),
        (
            "promotion secret/state preflight",
            promote_text,
            (
                "--require-aws-staging-secrets",
                "required_staging_secret_names",
                "module.secrets.aws_kms_key.secrets",
                "module.secrets.aws_kms_alias.secrets",
            ),
        ),
        (
            "pilot plan-role drift gate",
            workflow_text,
            (
                "verify_effective_staging_apply_policy.py",
                "config/staging_plan_iam_policy.yaml",
                "config/terraform_plan_state_access_policy.yaml",
                "AetherStagingPlanContract",
            ),
        ),
        (
            "merged-main authority gate",
            workflow_text,
            ("Require merged-main authority", 'GITHUB_REF_NAME" = main'),
        ),
        (
            "lifecycle plan-role drift gate",
            lifecycle_text,
            (
                "verify_effective_staging_apply_policy.py",
                "config/staging_plan_iam_policy.yaml",
                "config/terraform_plan_state_access_policy.yaml",
                "AetherStagingPlanContract",
            ),
        ),
    ):
        missing = _missing_all(text, tokens)
        if missing:
            errors.append(f"missing {label} contract evidence: {', '.join(missing)}")

    # Explicit markers make the intentional boundary reviewable.  The pilot
    # workflow must not activate any Kyber/GCP gate just because a full workflow
    # contains one elsewhere in the repository.
    try:
        lifecycle_doc = yaml.safe_load(lifecycle_text) or {}
        delivery_doc = yaml.safe_load(_read(ROOT / ".github/workflows/deploy.yml")) or {}
    except yaml.YAMLError as exc:
        errors.append(f"canonical staging delivery/lifecycle workflow is not valid YAML: {exc}")
        lifecycle_doc = {}
        delivery_doc = {}

    wake_apply = ((lifecycle_doc.get("jobs") or {}).get("wake-apply") or {})
    delivery_step = next(
        (
            step
            for step in wake_apply.get("steps") or []
            if step.get("id") == "delivery"
        ),
        {},
    )
    delivery_run = str(delivery_step.get("run") or "")
    for required in (
        "gh workflow run deploy.yml",
        "-f delivery_mode=deploy",
        '-f source_run_id="$RELEASE_RUN_ID"',
        '-f release_manifest_checksum="$RELEASE_MANIFEST_CHECKSUM"',
        "delivery_run_id=%s",
        "acquire_ok",
        "build_skipped",
        "deploy_ok",
        'test "$run_sha" = "$INTENDED_RELEASE_SHA"',
    ):
        if required not in delivery_run:
            errors.append(f"pilot lifecycle must hand the approved artifact to canonical delivery: missing {required}")

    rehearsal_steps = ((lifecycle_doc.get("jobs") or {}).get("rehearse") or {}).get("steps") or []
    evidence_download = next(
        (
            step
            for step in rehearsal_steps
            if step.get("with", {}).get("name")
            == "deployment-evidence-${{ needs.wake-apply.outputs.delivery_run_id }}"
        ),
        {},
    )
    if evidence_download.get("with", {}).get("run-id") != "${{ needs.wake-apply.outputs.delivery_run_id }}":
        errors.append("pilot rehearsal must consume deployment evidence from its exact canonical delivery run")
    migration_step = next(
        (
            step
            for step in rehearsal_steps
            if step.get("name") == "Verify delivered migration and resulting database revision"
        ),
        {},
    )
    if "aws ecs run-task" in str(migration_step.get("run") or ""):
        errors.append("pilot rehearsal must not run a second migration task after canonical delivery")
    build_job = ((delivery_doc.get("jobs") or {}).get("build") or {})
    if "acquire-release" not in (build_job.get("needs") or []):
        errors.append("canonical delivery build must be gated by immutable source-artifact acquisition")

    acquire = ((delivery_doc.get("jobs") or {}).get("acquire-release") or {})
    if "inputs.source_run_id != ''" not in str(acquire.get("if") or ""):
        errors.append("canonical delivery must acquire the exact release supplied to a staging rehearsal")

    if "PILOT_DEFERRED_GATES" not in workflow_text:
        errors.append("pilot path must declare PILOT_DEFERRED_GATES explicitly")
    for forbidden in (
        "check_kyber_staging_contract.py",
        "probe_kyber_staging_identity.py",
        "KYBER_GOOGLE_CLIENT_ID",
        "KYBER_GOOGLE_CLIENT_SECRET",
        "gcp_hosting_required",
    ):
        if forbidden in workflow_text:
            errors.append(f"pilot path must not activate deferred gate {forbidden}")

    terraform_root = _combined((ROOT / "deploy/aws/terraform/variables.tf", ROOT / "deploy/aws/terraform/main.tf"))
    if 'variable "deployment_lane"' not in terraform_root:
        errors.append("Terraform root has no deployment_lane variable; main integration must add it")
    elif not all(token in terraform_root for token in ('"full"', '"pilot"')):
        errors.append("Terraform deployment_lane validation must allow exactly full and pilot")
    if 'enable_social_connections = var.deployment_lane == "pilot" ? false : var.enable_social_connections' not in terraform_root:
        errors.append(
            "pilot lane must disable optional Auth0 social connections until external provider credentials are provisioned"
        )

    for label, paths, tokens in REQUIRED_SURFACES:
        text = _combined(paths).lower()
        missing = [token for token in tokens if token.lower() not in text]
        if missing:
            errors.append(f"missing {label} contract evidence: {', '.join(missing)}")

    secrets_source = _read(ROOT / "deploy/aws/terraform/modules/secrets/main.tf")
    missing_secret_names = _missing_all(secrets_source, STRIPE_SECRET_NAMES)
    if missing_secret_names:
        errors.append(
            "missing Stripe Terraform secret definitions: "
            + ", ".join(missing_secret_names)
        )

    ecs_source = _read(ROOT / "deploy/aws/terraform/modules/ecs/main.tf")
    missing_ecs = _missing_all(ecs_source, STRIPE_ENVIRONMENT)
    if missing_ecs:
        errors.append(
            "missing ECS Stripe runtime wiring (env/mounts): "
            + ", ".join(missing_ecs)
        )
    # Requiring the exact secret-name mapping in ECS prevents a price secret
    # from existing in Terraform while remaining absent from the task.
    missing_mount_names = _missing_all(ecs_source, STRIPE_REQUIRED_RUNTIME_SECRET_NAMES)
    if missing_mount_names:
        errors.append(
            "missing ECS Stripe secret mounts: " + ", ".join(missing_mount_names)
        )

    bootstrap = _read(ROOT / "scripts/bootstrap_aws_secrets.py")
    missing_bootstrap = _missing_all(bootstrap, STRIPE_SECRET_NAMES)
    if missing_bootstrap:
        errors.append(
            "bootstrap_aws_secrets.py does not name Stripe secrets: "
            + ", ".join(missing_bootstrap)
        )

    settings = _read(ROOT / "services/backend/config/settings.py")
    missing_settings = _missing_all(settings, STRIPE_ENVIRONMENT)
    if missing_settings:
        errors.append(
            "backend Stripe settings are missing required fields: "
            + ", ".join(missing_settings)
        )
    return errors


def validate_contract(workflow_path: Path = DEFAULT_WORKFLOW, lane: str = PILOT) -> dict[str, Any]:
    errors = find_errors(workflow_path, lane)
    if errors:
        raise ValueError("\n".join(errors))
    return {
        "contract": "pilot-staging",
        "version": 1,
        "profile": CANONICAL_PROFILE,
        LANE_TOKEN: lane,
        "aws_authorities": list(AUTHORITY_WORKFLOWS),
        "stripe_price_secret_names": list(
            f"aether/{name}" for name in STRIPE_REQUIRED_RUNTIME_SECRET_NAMES if name.startswith("stripe-price-")
        ),
        "deferred_gates": [
            "kyber_operator_workforce_identity",
            "gcp_hosting",
            "google_credentials",
        ],
        "secret_values_read": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument(f"--{LANE_TOKEN}", dest="lane", default=PILOT)
    parser.add_argument("--evidence-out", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    workflow_path = args.workflow if args.workflow.is_absolute() else ROOT / args.workflow
    try:
        evidence = validate_contract(workflow_path, args.lane)
    except ValueError as exc:
        print("pilot staging contract FAILED:", file=sys.stderr)
        for line in str(exc).splitlines():
            print(f"- {line}", file=sys.stderr)
        return 1

    if args.evidence_out:
        output = args.evidence_out if args.evidence_out.is_absolute() else ROOT / args.evidence_out
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    if args.as_json:
        print(json.dumps(evidence, sort_keys=True))
    else:
        print("pilot staging contract valid: profile=staging deployment_lane=pilot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
