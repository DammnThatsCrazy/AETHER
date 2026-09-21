"""Release workflows must validate pull requests without mutating them."""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

# The only workflow permitted to run `terraform apply`.
APPLY_WORKFLOW = "terraform-promote.yml"

# `terraform show -json` does not redact `sensitive = true` root variables, so
# every workflow that publishes plan JSON must route it through this first.
SANITISER = "scripts/release/sanitize_terraform_plan_json.py"

# Workflows held to `set -euo pipefail` by THIS file. deploy.yml belongs here
# because it is the one workflow that mutates ECS on a push to main.
STRICT_BASH_WORKFLOWS = (
    "infrastructure.yml",
    APPLY_WORKFLOW,
    "deploy.yml",
    "staging-state-reconcile.yml",
    "terraform-state-migrate.yml",
)
# Held to the identical rule by tests/unit/test_staging_lifecycle_controls.py.
STRICT_BASH_ELSEWHERE = ("staging-lifecycle.yml", "staging-ttl-guard.yml")

# `terraform apply` sites that live in a NESTED `.github/workflows` tree. GitHub
# only executes the directory at the repository root, so these never run — but
# they are git-tracked, and moving one into the live directory would restore
# whatever it contains (in this case an `-auto-approve` apply under `push: main`).
# They are enumerated so a NEW apply site anywhere in the repository fails the
# exclusivity test, rather than being tolerated by a root-only glob's silence.
QUARANTINED_APPLY_SITES = {
    "cicd/aether-cicd/.github/workflows/cd.yml",
    "cicd/aether-cicd/.github/workflows/demo-management.yml",
    "cicd/aether-cicd/.github/workflows/infrastructure.yml",
}
# Every profile the promotion workflow can dispatch, matching the parity
# restatement (cloud ∪ ephemeral-class). demo/preview are ephemeral-class and
# dispatchable; the apply environment mapping in the workflow must cover all
# six.
TF_PROFILES = (
    "staging", "production-lean", "production-scale", "enterprise-isolated",
    "demo", "preview",
)
# Triggers that fire without a human choosing to run the workflow.
AUTOMATIC_TRIGGERS = {
    "push",
    "pull_request",
    "pull_request_target",
    "schedule",
    "release",
    "repository_dispatch",
    "workflow_run",
    "check_run",
    "check_suite",
    "issue_comment",
}


def _workflow(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def _workflow_names() -> list[str]:
    return sorted(p.name for p in WORKFLOW_DIR.glob("*.y*ml"))


def _every_workflow_file() -> list[Path]:
    """Every `.github/workflows/*.yml` in the repository, nested trees included."""
    return sorted(
        path
        for path in ROOT.rglob("*.y*ml")
        if path.parent.name == "workflows"
        and path.parent.parent.name == ".github"
        and "node_modules" not in path.parts
        # .claude/ is git-ignored local scratch (agent worktrees clone the
        # repo there); nothing under it is tracked, so nothing under it can
        # ever reach GitHub Actions.
        and ".claude" not in path.parts
    )


def _sanitiser():
    """Import scripts/release/sanitize_terraform_plan_json.py by path."""
    spec = importlib.util.spec_from_file_location("_plan_sanitiser", ROOT / SANITISER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow_yaml(name: str) -> dict:
    return yaml.safe_load(_workflow(name))


def _triggers(doc: dict) -> set[str]:
    # YAML 1.1 parses the bare key `on:` as the boolean True.
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    if isinstance(on, dict):
        return set(on)
    return set()


def _steps(doc: dict, job: str) -> list[dict]:
    return list(doc["jobs"][job].get("steps") or [])


def _runs(doc: dict, job: str) -> list[str]:
    return [s["run"] for s in _steps(doc, job) if s.get("run")]


def _job_script(doc: dict, job: str) -> str:
    """Every `run:` in a job, in step order, as one script."""
    return "\n".join(_runs(doc, job))


def _all_run_blocks(doc: dict):
    for job_name, job in (doc.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            if step.get("run"):
                yield job_name, step.get("name", "<unnamed>"), step["run"]


def _logical_lines(run: str) -> list[str]:
    """Join backslash continuations so a piped command is one line."""
    return re.sub(r"\\\n\s*", " ", run).splitlines()


def _is_piped(line: str) -> bool:
    """True when the line contains a shell pipe (and not just `||`)."""
    return "|" in line.replace("||", "")


def _enables_pipefail(run: str) -> bool:
    """True only for a real `set ... pipefail`; a comment saying so does not count."""
    return any(
        re.match(r"set\s+-\S", stripped) and "pipefail" in stripped
        for stripped in (line.strip() for line in run.splitlines())
        if not stripped.startswith("#")
    )


def test_native_sdk_validation_runs_on_pr_finalization():
    workflow = _workflow("sdk-release-validation.yml")
    doc = _workflow_yaml("sdk-release-validation.yml")
    assert _triggers(doc) == {"push", "pull_request", "workflow_dispatch"}
    pull_request = doc.get("on", doc.get(True))["pull_request"]
    assert pull_request["types"] == ["ready_for_review"]
    assert "gradle assembleRelease publishToMavenLocal" in workflow
    assert "xcodebuild test" in workflow
    assert "xcrun simctl list devices available -j" in workflow
    assert "steps.simulator.outputs.udid" in workflow
    assert "name=iPhone 16" not in workflow
    assert "pod spec lint packages/ios/AetherSDK.podspec" in workflow


def test_shared_sdk_parity_changes_trigger_all_sdk_jobs():
    workflow = _workflow("sdk-release-validation.yml")
    assert workflow.count("packages/shared/sdk-parity.json") == 2
    assert workflow.count("scripts/release/sdk_conformance.py") == 2


def test_hardening_gate_is_read_only_and_never_rewrites_pr_history():
    workflow = _workflow("hardening-release-gate.yml")
    assert "contents: read" in workflow
    for forbidden in (
        "docs_drift.py --update",
        "git push",
        "git commit",
        "git reset --soft",
        "force-with-lease",
    ):
        assert forbidden not in workflow
    assert "run: make ci-check" in workflow
    assert "run: make release-gate" in workflow
    assert 'git rev-parse HEAD' in workflow
    assert '"sha":"%s"' in workflow


def test_hardening_release_gate_is_not_an_ordinary_pr_check():
    doc = _workflow_yaml("hardening-release-gate.yml")
    triggers = _triggers(doc)
    assert "pull_request" not in triggers
    assert {"workflow_dispatch", "release", "workflow_call"} <= triggers


# ---------------------------------------------------------------------------
# Immutable deploy workflow (deploy.yml) — PR #454 review-finding pins
# ---------------------------------------------------------------------------


def test_deploy_maps_api_role_to_backend_service():
    workflow = _workflow("deploy.yml")
    assert '$([ "$role" = api ] && echo backend || echo "$role")' in workflow


def test_deploy_installs_python_and_pyyaml_before_parsing_the_profile():
    workflow = _workflow("deploy.yml")
    deploy_job = workflow.split("\n  deploy:\n", 1)[1]
    assert "actions/setup-python" in deploy_job
    assert "pip install pyyaml" in deploy_job


def test_deploy_applies_packaged_migrations_before_rollout():
    workflow = _workflow("deploy.yml")
    assert '"alembic","upgrade","head"' in workflow.replace('\\"', '"')
    assert "aws ecs wait tasks-stopped" in workflow
    assert "packaged migration task failed" in workflow


def test_deploy_gates_on_readiness_and_golden_path_smoke():
    workflow = _workflow("deploy.yml")
    assert "/v1/ready" in workflow
    assert "scripts/smoke_test.py" in workflow
    # Gates run before the deployment evidence artifact is uploaded.
    evidence_upload = workflow.index("deployment-evidence-${{ github.run_id }}")
    assert workflow.index("/v1/ready") < evidence_upload
    assert workflow.index("scripts/smoke_test.py") < evidence_upload


def test_staging_delivery_validates_its_runtime_iam_delta_and_api_host_fallback():
    workflow = _workflow("deploy.yml")
    assert "check_staging_application_delivery_policy.py" in workflow
    assert "python -m pip install --disable-pip-version-check pyyaml" in workflow
    assert "vars.ALB_DNS_NAME || secrets.TF_DOMAIN_NAME" in workflow
    assert "aws ecs run-task" in workflow
    assert "aws ecs describe-tasks" in workflow
    assert "aws s3 sync" in workflow
    assert "aws s3 cp" in workflow


def test_staging_delivery_rejects_a_live_task_lane_mismatch_before_mutation():
    workflow = _workflow("deploy.yml")
    lane_check = workflow.index("Verify the current staging task-definition lane before mutation")
    mutation = workflow.index("Apply packaged migrations, then register exact task revision")
    assert lane_check < mutation
    assert "check_staging_task_definition_contract.py" in workflow[lane_check:mutation]
    assert "DEPLOYMENT_LANE" in workflow[lane_check:mutation]


def test_staging_smoke_uses_the_authoritative_proof_environment_and_fails_closed():
    workflow = _workflow("staging-smoke.yml")
    assert "  push:" not in workflow
    assert "workflow_dispatch:" in workflow
    assert "environment: staging" in workflow
    assert "AETHER_API_URL" in workflow
    assert "AETHER_API_KEY" in workflow
    assert "PROOF_TENANT_ID" in workflow
    assert "PROOF_WORKSPACE_ID" in workflow
    assert "vars.AETHER_API_URL || format('https://{0}', secrets.TF_DOMAIN_NAME)" in workflow
    assert "secrets.SMOKE_API_KEY" in workflow
    assert "needs.preflight.result == 'success'" in workflow
    assert "skipping staging smoke test" not in workflow
    assert "AETHER_STAGING_URL" not in workflow
    assert "secrets.PROOF_TENANT_ID" not in workflow
    assert "secrets.PROOF_WORKSPACE_ID" not in workflow
    assert "check_staging_secret_payload_contract.py --lane pilot" in workflow
    assert "secrets.AWS_STAGING_SECRET_PREFLIGHT_ROLE_ARN" in workflow
    assert "secrets.AWS_TERRAFORM_PLAN_ROLE_ARN" in workflow
    assert "AetherStagingPlan" in workflow
    assert "check_staging_task_definition_contract.py --lane pilot" in workflow
    assert "Load the pilot Stripe test key without logging it" in workflow
    assert 'echo "::add-mask::$stripe_key"' in workflow
    assert "STRIPE_SECRET_KEY" in workflow


def test_staging_build_only_release_is_available_without_ecs_mutation():
    deploy = _workflow_yaml("deploy.yml")
    deploy_text = _workflow("deploy.yml")
    triggers = deploy.get("on", deploy.get(True))
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["delivery_mode"]["options"] == ["deploy", "build-only"]
    assert "build-only delivery is limited to staging" in deploy_text
    assert "inputs.delivery_mode == 'deploy'" in deploy_text

    lifecycle = _workflow("staging-lifecycle.yml")
    assert "Successful `Immutable delivery` build-only or deployed run" in lifecycle
    assert "Build immutable release once" in lifecycle
    assert "has no successful immutable build job" in lifecycle


def test_stripe_smoke_uses_form_encoded_confirmed_test_payment():
    smoke = (ROOT / "scripts/smoke/stripe-connector.ts").read_text(encoding="utf-8")
    assert "URLSearchParams" in smoke
    assert "application/x-www-form-urlencoded" in smoke
    assert "JSON.stringify(payload)" not in smoke
    assert "path.replace(/^\\/+/, '')" in smoke
    assert "https://api.stripe.com/v1/" in smoke
    assert "payment_method: 'pm_card_visa'" in smoke
    assert "confirm: true" in smoke
    assert "expand[]=latest_charge" in smoke


def test_production_status_workflow_binds_the_canonical_build_and_runtime_links():
    workflow = _workflow("amplify-status-production.yml")
    assert "--repository \"$AMPLIFY_REPOSITORY\"" in workflow
    assert "appRoot: frontend/status" in workflow
    assert "npm run build --workspace=frontend/status" in workflow
    assert "VITE_STATUS_API_URL=https://api.olympuslabsml.com/health" in workflow
    assert "VITE_STATUS_DOCS_URL=https://docs.olympuslabsml.com" in workflow
    assert "VITE_STATUS_AETHER_MARKETING_URL=https://aether.olympuslabsml.com" in workflow
    assert "--stage PRODUCTION" in workflow


def test_production_status_waits_for_exact_main_integration_authority():
    document = _workflow_yaml("amplify-status-production.yml")
    workflow = _workflow("amplify-status-production.yml")
    gate = document["jobs"]["verify-main-integration"]
    deploy = document["jobs"]["deploy"]
    assert gate["name"] == "Verify Main integration authority for exact commit"
    assert "checks: read" in workflow
    assert "Main integration authority" in workflow
    assert deploy["needs"] == "verify-main-integration"
    assert deploy["if"] == "needs.verify-main-integration.result == 'success'"
    assert "commits/$EXPECTED_COMMIT_SHA/check-runs" in workflow
    assert "conclusion" in workflow


def test_staging_secret_policy_audits_use_the_separate_inspection_role():
    for name in ("terraform-promote.yml", "pilot-staging.yml", "staging-smoke.yml"):
        document = _workflow_yaml(name)
        text = _workflow(name)
        assert document["jobs"]
        assert "AWS_TERRAFORM_PLAN_ROLE_ARN" in text
        assert "verify_effective_staging_apply_policy.py" in text
        assert "Verify staging IAM inspection role assumption" in text
        assert text.index("Configure AWS inspection credentials") < text.rindex(
            "AWS_STAGING_SECRET_PREFLIGHT_ROLE_ARN"
        ), name
        assert "AetherStagingSecretPreflightContract" in text
        assert "role-to-assume: " + "$" + "{{ secrets.AWS_TERRAFORM_PLAN_ROLE_ARN }}" in text

    lifecycle = _workflow_yaml("staging-lifecycle.yml")
    lifecycle_text = _workflow("staging-lifecycle.yml")
    assert lifecycle["jobs"]["select-profile"]["steps"]
    assert (
        "TARGET_ROLE_ARN: "
        + "$"
        + "{{ secrets.AWS_STAGING_LIFECYCLE_ROLE_ARN }}"
        in lifecycle_text
    )
    assert "role-to-assume: " + "$" + "{{ secrets.AWS_TERRAFORM_PLAN_ROLE_ARN }}" in lifecycle_text
    assert "Verify staging IAM inspection role assumption" in lifecycle_text
    assert lifecycle_text.index("verify_effective_staging_lifecycle_policy.py") < lifecycle_text.index(
        "Verify lifecycle role assumption before dispatch"
    )
    assert "if: inputs.action == 'apply-wake' || inputs.action == 'full-rehearsal'" in lifecycle_text


def test_sleep_paths_do_not_depend_on_application_secret_values():
    promote = _workflow_yaml("terraform-promote.yml")
    promote_text = _workflow("terraform-promote.yml")
    preflight = promote["jobs"]["staging-secret-payload-preflight"]
    apply_if = promote["jobs"]["apply"]["if"]
    assert preflight["if"] == "inputs.profile == 'staging' && inputs.secret_preflight_required"
    assert "inputs.staging_state == 'asleep'" in promote_text
    assert "steps.reviewed.outputs.staging_state != 'asleep'" in promote_text
    assert "inputs.secret_preflight_required == false" in apply_if
    assert "inputs.staging_state == 'asleep'" not in apply_if

    lifecycle_text = _workflow("staging-lifecycle.yml")
    assert "-f staging_state=asleep" in lifecycle_text
    assert "no verified sleep plan_run_id" in lifecycle_text


def test_pilot_sleep_paths_skip_non_cleanup_preflights_but_keep_authority():
    document = _workflow_yaml("pilot-staging.yml")
    text = _workflow("pilot-staging.yml")
    credential_job = document["jobs"]["credential-preflight"]
    secret_job = document["jobs"]["secret-payload-preflight"]
    amplify_job = document["jobs"]["amplify-preflight"]
    assert "inputs.action != 'plan-sleep'" in credential_job["if"]
    assert "inputs.action != 'apply-sleep'" in credential_job["if"]
    assert "inputs.action != 'plan-sleep'" in secret_job["if"]
    assert "inputs.action != 'apply-sleep'" in secret_job["if"]
    assert "secret-payload-preflight.result == 'skipped'" in text
    assert "inputs.action != 'plan-sleep'" in amplify_job["if"]
    assert "inputs.action != 'apply-sleep'" in amplify_job["if"]
    dispatch_if = document["jobs"]["dispatch-authority"]["if"]
    for job_name in ("amplify-preflight", "dispatch-authority"):
        job = document["jobs"][job_name]
        assert job["if"].startswith("always()")
        assert "secret-payload-preflight" in job["needs"]
    assert "credential-preflight.result == 'skipped'" in dispatch_if
    assert "amplify-preflight.result == 'skipped'" in dispatch_if


def test_staging_reconciliation_discovers_all_managed_price_resources():
    text = _workflow("staging-state-reconcile.yml")
    for name in (
        "stripe-price-alpha",
        "stripe-price-beta",
        "stripe-price-gamma",
        "stripe-price-delta",
        "stripe-price-epsilon",
        "stripe-price-omicron",
        "stripe-price-omega",
    ):
        assert name in text
    assert "Discover pre-existing Stripe price secrets for state reconciliation" in text
    assert "steps.discover-price-secrets.outputs.secret_names" in text
    assert "ResourceNotFoundException" in text
    assert "the secret value was not read" in text


def test_legacy_price_secrets_have_an_explicit_metadata_only_rekey_path():
    text = _workflow("staging-state-reconcile.yml")
    assert "migrate_legacy_secret_kms" in text
    assert "confirm_legacy_secret_kms" in text
    assert "MIGRATE-STAGING-SECRETS" in text
    assert 'aws secretsmanager update-secret' in text
    assert '--kms-key-id "$STAGING_SECRETS_KMS_KEY_ARN"' in text
    assert "secretsmanager get-secret-value" not in text


def test_pilot_dispatch_binds_to_the_exact_created_run():
    text = _workflow("pilot-staging.yml")
    assert "before_id" not in text
    assert "workflow_runs[0]" not in text
    assert text.count("actions/runs/([0-9]+)") == text.count("gh workflow run")
    assert "dispatch did not return its created run URL" in text


def test_pilot_smoke_validates_the_configured_stripe_price_catalog():
    text = _workflow("staging-smoke.yml")
    assert "Load pilot Stripe prices without logging values" in text
    assert "Validate pilot Stripe prices against the configured test account" in text
    assert "python scripts/validate_stripe.py --skip-webhook" in text
    for variable in (
        "STRIPE_PRICE_ALPHA",
        "STRIPE_PRICE_BETA",
        "STRIPE_PRICE_GAMMA",
        "STRIPE_PRICE_DELTA",
        "STRIPE_PRICE_EPSILON",
        "STRIPE_PRICE_OMICRON",
        "STRIPE_PRICE_OMEGA",
    ):
        assert variable in text
    assert "load_optional_price" in text
    assert "ResourceNotFoundException" in text


def test_infrastructure_staging_audits_the_dedicated_plan_role():
    text = _workflow("infrastructure.yml")
    document = _workflow_yaml("infrastructure.yml")
    assert (
        "AWS_TERRAFORM_PLAN_ROLE_ARN: "
        + "$"
        + "{{ secrets.AWS_TERRAFORM_PLAN_ROLE_ARN }}"
        in text
    )
    staging_gate = text[text.index("Verify effective staging plan IAM contract"):]
    assert "--role-arn \"$AWS_TERRAFORM_PLAN_ROLE_ARN\"" in staging_gate
    assert "--expected-role AetherStagingPlan" in staging_gate
    assert (
        "role-to-assume: "
        + "${{ matrix.profile == 'staging' && secrets.AWS_TERRAFORM_PLAN_ROLE_ARN || secrets.AWS_INFRA_ROLE_ARN }}"
        in text
    )
    triggers = document.get("on", document.get(True))
    dispatch_inputs = triggers["workflow_dispatch"]["inputs"]
    assert dispatch_inputs["deployment_lane"]["default"] == "pilot"
    assert "--lane \"$DEPLOYMENT_LANE\"" in text
    remote_plan = _job_script(document, "remote-plan")
    assert 'plan_args+=("-var=deployment_lane=${DEPLOYMENT_LANE}")' in remote_plan


def test_deploy_builds_each_spa_with_its_own_auth0_client_and_endpoints():
    workflow = _workflow("deploy.yml")
    assert "secrets.AETHER_AUTH0_CLIENT_ID" in workflow
    assert "secrets.KYBER_AUTH0_CLIENT_ID" in workflow
    assert "vars.KYBER_GOOGLE_CLIENT_ID" in workflow
    assert "secrets.KYBER_GOOGLE_CLIENT_ID" in workflow
    assert "vars.KYBER_API_BASE_URL" in workflow
    assert "vars.KYBER_WS_BASE_URL" in workflow
    kyber_build = workflow.split("npm --workspace frontend/kyber run build")[0]
    assert 'VITE_AUTH0_CLIENT_ID="$KYBER_AUTH0_CLIENT_ID"' in kyber_build
    assert 'VITE_KYBER_ENV=staging' in kyber_build
    assert 'VITE_OIDC_AUTHORITY="https://accounts.google.com"' in kyber_build
    assert 'VITE_OIDC_CLIENT_ID="$KYBER_GOOGLE_CLIENT_ID"' in kyber_build
    assert 'VITE_OIDC_REDIRECT_URI="$KYBER_API_BASE_URL/v1/kyber/auth/callback"' in kyber_build
    assert 'VITE_API_BASE_URL="$KYBER_API_BASE_URL"' in kyber_build
    assert 'VITE_WS_BASE_URL="$KYBER_WS_BASE_URL"' in kyber_build


def test_deploy_recovers_an_immutable_tag_publish_race():
    workflow = _workflow("deploy.yml")
    assert "continue-on-error: true" in workflow
    assert "id: backend-race" in workflow
    assert "steps.backend.outcome == 'failure'" in workflow
    assert "imageTag=\"${GITHUB_SHA}\"" in workflow
    assert "for attempt in 1 2 3 4 5 6 7 8 9 10 11 12" in workflow
    assert "sleep 5" in workflow
    assert "no immutable image exists" in workflow
    assert "RACE_DIGEST: ${{ steps.backend-race.outputs.digest }}" in workflow
    assert 'digest="${EXISTING_DIGEST:-${RACE_DIGEST:-${BUILT_DIGEST:-}}}"' in workflow


def test_deploy_inspects_the_published_image_before_releasing_it():
    """The release manifest must not bless an image whose migration runtime is broken."""
    workflow = _workflow("deploy.yml")
    assert "Validate published backend migration runtime" in workflow
    assert 'docker pull "$image"' in workflow
    assert 'docker run --rm --entrypoint python "$image"' in workflow
    assert "import psycopg2" in workflow
    assert 'Path("alembic.ini").is_file()' in workflow
    assert 'Path("alembic/env.py").is_file()' in workflow


def test_deploy_verifies_source_run_identity_before_trusting_artifacts():
    workflow = _workflow("deploy.yml")
    assert "actions/runs/${SOURCE_RUN_ID}" in workflow
    assert ".github/workflows/deploy.yml'" in workflow
    assert "concluded ${run_conclusion}, not success" in workflow
    assert "no successful staging deploy job" in workflow
    # The verification step precedes the artifact download in the acquire job.
    verify = workflow.index("Verify source run identity")
    download = workflow.index("run-id: ${{ inputs.source_run_id }}")
    assert verify < download


def test_deploy_polls_the_authority_that_exists_for_each_trigger():
    workflow = _workflow("deploy.yml")
    assert 'if [ "${GITHUB_EVENT_NAME}" = "push" ] || [ "${TARGET_ENV}" = "staging" ]; then' in workflow
    assert '[ "${TARGET_ENV}" = "staging" ]' in workflow
    assert 'required_checks=("Main integration authority")' in workflow
    assert "required_checks=(validate)" in workflow
    # A staging dispatch does not trigger Repo Health's nightly/dispatch
    # aggregate `validate`, so it must reuse the merged-main authority instead
    # of failing closed on a legitimately skipped check.
    assert "intentionally skipped job as a failed verification" in workflow
    assert "timeout-minutes: 35" in workflow
    assert "deadline=$((SECONDS + 2040))" in workflow


def test_deploy_never_interpolates_inputs_into_run_scripts():
    for name in ("deploy.yml", "terraform-promote.yml"):
        workflow = _workflow(name)
        for line in workflow.splitlines():
            stripped = line.strip()
            if stripped.startswith(("test -n '${{", "test \"$(cat")):
                assert "${{" not in stripped, f"{name}: quoted inline input: {stripped}"


# ---------------------------------------------------------------------------
# Credential gating (deploy.yml / TTL guards / infrastructure.yml) — PR #519
# pins. The secrets context is unavailable in job/step `if:` conditions, so
# every credential gate launders the secret through an env binding, publishes a
# boolean output, and gates on that output. These tests pin BOTH branches:
# credential-present steps must gate on armed == true, and credential-absent
# runs must skip every credential-gated step and emit a loud not-armed notice —
# never fail at configure-aws-credentials and never silently go green.
# ---------------------------------------------------------------------------


def test_deploy_gates_build_and_deploy_on_delivery_armed_output():
    doc = _workflow_yaml("deploy.yml")

    armed = doc["jobs"]["delivery-armed"]
    assert armed["environment"] == (
        "${{ github.event_name == 'push' && 'staging' || inputs.environment }}"
    )
    assert armed["outputs"] == {"armed": "${{ steps.check.outputs.armed }}"}
    check = next(s for s in armed["steps"] if s.get("id") == "check")
    assert check["env"]["AWS_DEPLOY_ROLE_ARN"] == "${{ secrets.AWS_DEPLOY_ROLE_ARN }}"
    check_run = check["run"]
    assert "armed=true" in check_run
    assert "armed=false" in check_run
    # The secret is laundered through env; it must never be interpolated into
    # a run script, where an injected value could be evaluated.
    assert "secrets.AWS_DEPLOY_ROLE_ARN" not in check_run

    build = doc["jobs"]["build"]
    assert "delivery-armed" in build["needs"]
    assert build["if"] == (
        "(github.event_name == 'push' || inputs.environment == 'staging')"
        " && needs.delivery-armed.outputs.armed == 'true'"
    )

    not_armed = doc["jobs"]["delivery-not-armed"]
    assert not_armed["needs"] == ["delivery-armed"]
    assert not_armed["if"] == "needs.delivery-armed.outputs.armed == 'false'"
    assert "::notice title=Delivery not armed" in _job_script(doc, "delivery-not-armed")
    # The notice must be explicit that nothing was deployed — never read a
    # skipped build as a green delivery.
    assert "NOT a claim that a release exists" in _job_script(doc, "delivery-not-armed")

    deploy = doc["jobs"]["deploy"]
    assert "delivery-armed" in deploy["needs"]
    assert "needs.delivery-armed.outputs.armed == 'true'" in deploy["if"]


def test_deploy_armed_check_binds_the_role_before_any_aws_step():
    """The armed detection must be its own job that runs before build/deploy so
    a credential-less run never reaches configure-aws-credentials."""
    doc = _workflow_yaml("deploy.yml")
    names = list(doc["jobs"])
    assert names.index("delivery-armed") < names.index("build")
    assert names.index("delivery-armed") < names.index("deploy")
    build = doc["jobs"]["build"]
    assert build["needs"][0] == "require-ci-green"
    assert build["needs"][1] == "delivery-armed"


def test_ttl_guards_are_loud_noops_without_the_lifecycle_role():
    for name in ("staging-ttl-guard.yml", "ephemeral-ttl-guard.yml"):
        doc = _workflow_yaml(name)
        steps = doc["jobs"]["guard"]["steps"]

        secret_name = (
            "AWS_STAGING_LIFECYCLE_ROLE_ARN"
            if name == "staging-ttl-guard.yml"
            else "AWS_EPHEMERAL_LIFECYCLE_ROLE_ARN"
        )
        check = next(s for s in steps if s.get("id") == "check-armed")
        assert check["env"][secret_name] == f"${{{{ secrets.{secret_name} }}}}"
        check_run = check["run"]
        assert "armed=true" in check_run
        assert "armed=false" in check_run
        assert f"secrets.{secret_name}" not in check_run

        # Every credential-gated step reads the same armed output, and the AWS
        # credential assumption is among them.
        gated = [
            s for s in steps
            if s.get("if") == "steps.check-armed.outputs.armed == 'true'"
        ]
        assert gated, f"{name}: no credential-gated steps found"
        assert any(
            str(s.get("uses", "")).startswith("aws-actions/configure-aws-credentials")
            for s in gated
        ), f"{name}: credential assumption is not armed-gated"

        not_armed = next(
            s for s in steps
            if s.get("if") == "steps.check-armed.outputs.armed == 'false'"
        )
        notice = not_armed["run"]
        assert "::notice title=" in notice
        assert "NO-OP" in notice
        # The notice is the OPPOSITE of an "environment is asleep" claim.
        assert "NOT a claim" in notice


def test_staging_ttl_guard_inspects_lifecycle_policy_with_plan_role_first():
    text = _workflow("staging-ttl-guard.yml")
    assert "AWS_TERRAFORM_PLAN_ROLE_ARN" in text
    assert "AetherStagingPlan" in text
    assert text.index("Configure AWS inspection credentials") < text.index(
        "Verify effective lifecycle IAM policy before enforcement"
    )
    assert text.index("Verify effective lifecycle IAM policy before enforcement") < text.index(
        "Configure AWS lifecycle credentials"
    )
    assert text.index("Verify staging IAM inspection role assumption") < text.index(
        "Verify effective lifecycle IAM policy before enforcement"
    )
    assert "Verify lifecycle role assumption before TTL enforcement" in text


def test_staging_ttl_guard_blocking_alert_keys_on_armed_output_not_readings():
    """The blocking alert runs unconditionally and keys its not-armed branch on
    the armed output directly — never on the lease readings being unset. An
    armed run whose state/config steps failed must fall through to the blocking
    error, not into the not-armed notice."""
    doc = _workflow_yaml("staging-ttl-guard.yml")
    alert = next(
        s for s in doc["jobs"]["guard"]["steps"]
        if "Blocking alert" in s.get("name", "")
    )
    assert alert["if"] == "always()"
    assert alert["env"]["ARMED"] == "${{ steps.check-armed.outputs.armed }}"
    assert 'if [ "${ARMED:-}" = false ]' in alert["run"]


def test_ephemeral_ttl_guard_blocking_alert_only_when_armed_and_expired():
    doc = _workflow_yaml("ephemeral-ttl-guard.yml")
    alert = next(
        s for s in doc["jobs"]["guard"]["steps"]
        if "Blocking alert" in s.get("name", "")
    )
    assert "steps.check-armed.outputs.armed == 'true'" in alert["if"]
    assert "steps.decision.outputs.expired == 'true'" in alert["if"]


def test_infrastructure_promotion_gate_reports_not_armed_without_credentials():
    """A credentialed remote-plan dispatch must fail closed at its final gate."""
    doc = _workflow_yaml("infrastructure.yml")
    steps = doc["jobs"]["require-production-credentials"]["steps"]
    enforce = next(
        s for s in steps if s.get("name") == "Enforce credentialed remote plans"
    )
    assert enforce["if"] == "always()"
    assert "READINESS_RESULT" in enforce["env"]
    assert "CONFIGURED" in enforce["env"]
    # The enforce step carries all three fail-closed checks.
    assert enforce["run"].count("exit 1") == 4


# ---------------------------------------------------------------------------
# Terraform promotion (terraform-promote.yml / variables.tf) — pins
# ---------------------------------------------------------------------------


def test_terraform_promote_passes_inputs_via_env_blocks():
    workflow = _workflow("terraform-promote.yml")
    assert "'${{ inputs.plan_checksum }}'" not in workflow
    assert "'${{ inputs.plan_run_id }}'" not in workflow
    assert "'${{ inputs.profile }}'" not in workflow
    assert "PLAN_CHECKSUM: ${{ inputs.plan_checksum }}" in workflow
    assert 'test "$(sha256sum reviewed.tfplan | cut -d\' \' -f1)" = "$PLAN_CHECKSUM"' in workflow


def test_terraform_promote_uses_remote_backend_in_plan_and_apply():
    workflow = _workflow("terraform-promote.yml")
    # The staging collision guard initializes the same remote backend before
    # the account-level ECS role bootstrap, in addition to plan and apply.
    assert workflow.count('-backend-config="bucket=${TF_STATE_BUCKET}"') == 3
    assert workflow.count('-backend-config="key=profiles/${PROFILE}/terraform.tfstate"') == 3
    versions = (ROOT / "deploy/aws/terraform/versions.tf").read_text(
        encoding="utf-8"
    )
    assert 'backend "s3" {}' in versions


def test_terraform_promote_requires_release_digest_inputs():
    workflow = _workflow("terraform-promote.yml")
    assert "backend_image_digest:" in workflow
    assert "ml_image_digest:" in workflow
    assert '-var "backend_image_digest=${BACKEND_IMAGE_DIGEST}"' in workflow
    assert '-var "ml_image_digest=${ML_IMAGE_DIGEST}"' in workflow


def test_image_digest_variables_have_no_mutable_defaults():
    variables = (ROOT / "deploy/aws/terraform/variables.tf").read_text(
        encoding="utf-8"
    )
    assert 'default     = "sha256:' not in variables
    assert "sha256:0000000000000000" not in variables


# ---------------------------------------------------------------------------
# Founding-tenant release gate (Makefile) — durable suites are not optional
# ---------------------------------------------------------------------------


def test_founding_release_gate_requires_durable_suites_or_hosted_evidence():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    gate = makefile.split("founding-tenant-release-gate:", 1)[1]
    gate = gate.split("\nvalidate-founding-tenant-surface:", 1)[0]
    for target in ("integration-durable", "integration-faults",
                   "runtime-readiness-gate", "staging-preflight"):
        assert target in gate, f"founding gate lost required suite {target}"
    # The only substitute for running the suites is hosted evidence verified
    # by collect_evidence.py in fail-closed release mode.
    assert "FOUNDING_GATE_HOSTED_EVIDENCE" in gate
    assert "--release-mode" in gate
    # No bare, always-exit-0 evidence call on the hosted path.
    assert "collect_evidence.py --release-mode" in gate


def test_durable_integration_uses_read_only_repository_test_runner():
    compose = (ROOT / "deploy/integration/docker-compose.durable.yml").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "integration-tests:" in compose
    assert "source: ../.." in compose
    assert "target: /workspace" in compose
    assert "working_dir: /workspace" in compose
    assert "entrypoint: []" in compose
    assert "AUTHORITATIVE_CONSENT_ENFORCEMENT_ENABLED: \"false\"" in compose
    assert "TENANT_COMPLIANCE_POLICY_ENABLED: \"false\"" in compose
    assert "tests/integration/test_batch_endpoint.py" in makefile
    assert "run --rm integration-tests" in makefile


# ---------------------------------------------------------------------------
# Infrastructure Profiles (infrastructure.yml) is validate-and-plan only, and
# the reviewed promotion workflow is the single production apply path.
# ---------------------------------------------------------------------------


def test_infrastructure_workflow_never_applies_terraform():
    doc = _workflow_yaml("infrastructure.yml")
    assert "apply-production-lean" not in doc["jobs"], (
        "the automatic production apply job is back in infrastructure.yml"
    )
    for job_name, step_name, run in _all_run_blocks(doc):
        where = f"infrastructure.yml:{job_name}:{step_name}"
        assert "terraform apply" not in run, f"{where} applies terraform"
        assert "-auto-approve" not in run, f"{where} auto-approves terraform"
    # Nothing in this workflow mutates infrastructure, so nothing may claim a
    # deployment environment (which is what confers apply-time credentials).
    for job_name, job in doc["jobs"].items():
        assert "environment" not in job, (
            f"infrastructure.yml:{job_name} claims a deployment environment "
            "but this workflow must never apply"
        )


def test_no_automatically_triggered_workflow_reaches_a_terraform_apply():
    offenders = []
    for name in _workflow_names():
        doc = _workflow_yaml(name)
        automatic = _triggers(doc) & AUTOMATIC_TRIGGERS
        if not automatic:
            continue
        for job_name, step_name, run in _all_run_blocks(doc):
            if "terraform apply" in run:
                offenders.append(f"{name}:{job_name}:{step_name} via {sorted(automatic)}")
    assert offenders == [], (
        "terraform apply is reachable from an automatic trigger: " + "; ".join(offenders)
    )


def test_terraform_apply_lives_only_in_the_reviewed_promotion_workflow():
    """Repo-wide, not just the live directory.

    Globbing only `ROOT/.github/workflows` asserted an exclusivity it never
    checked: a nested `.github/workflows` tree could hold a push-to-main
    `terraform apply -auto-approve` and a single `git mv` would make it live.
    """
    live, quarantined = set(), set()
    for path in _every_workflow_file():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            continue
        if not any("terraform apply" in run for _j, _s, run in _all_run_blocks(doc)):
            continue
        relative = path.relative_to(ROOT).as_posix()
        if path.parent == WORKFLOW_DIR:
            live.add(relative)
        else:
            quarantined.add(relative)

    assert live == {f".github/workflows/{APPLY_WORKFLOW}"}, (
        f"unexpected live terraform apply sites: {sorted(live)}"
    )
    # Nested apply sites are named, not tolerated by omission. `<=` so that
    # DELETING one passes and ADDING one fails.
    assert quarantined <= QUARANTINED_APPLY_SITES, (
        "a terraform apply appeared in a nested workflow tree that no one has "
        f"reviewed: {sorted(quarantined - QUARANTINED_APPLY_SITES)}"
    )
    # Everything on the quarantine list really is outside the live directory —
    # that non-liveness is the entire reason it is only quarantined.
    for relative in QUARANTINED_APPLY_SITES:
        path = ROOT / relative
        if path.exists():
            assert path.parent != WORKFLOW_DIR, (
                f"{relative} moved into the live workflow directory, which would "
                "restore a push-to-main auto-apply"
            )
    # ...and the one live applier is dispatch-only, so no ref, tag, path or
    # timer can start an apply.
    assert _triggers(_workflow_yaml(APPLY_WORKFLOW)) == {"workflow_dispatch"}


def test_promotion_apply_consumes_a_stored_plan_and_never_replans():
    doc = _workflow_yaml(APPLY_WORKFLOW)
    apply_script = _job_script(doc, "apply")
    plan_script = _job_script(doc, "plan")
    assert "terraform plan" in plan_script, "the plan job stopped planning"
    assert "terraform plan" not in apply_script, "the apply job re-plans"
    assert "-auto-approve" not in apply_script
    assert "terraform apply -input=false reviewed.tfplan" in apply_script, (
        "apply must consume the stored binary plan file, not a fresh plan"
    )
    # The binary plan is produced by the plan job and travels as an artifact.
    assert "-out=reviewed.tfplan" in plan_script
    downloads = [
        s for s in _steps(doc, "apply") if str(s.get("uses", "")).startswith("actions/download-artifact")
    ]
    assert len(downloads) == 1, "apply must obtain the plan from exactly one artifact download"
    assert downloads[0]["with"]["run-id"] == "${{ inputs.plan_run_id }}"


def test_promotion_plan_and_apply_use_distinct_aws_roles():
    doc = _workflow_yaml(APPLY_WORKFLOW)

    def role(job: str) -> str:
        roles = [
            s["with"]["role-to-assume"]
            for s in _steps(doc, job)
            if str(s.get("uses", "")).startswith("aws-actions/configure-aws-credentials")
        ]
        assert len(roles) == 1, f"{job} assumes {len(roles)} AWS roles"
        return roles[0]

    plan_role, apply_role = role("plan"), role("apply")
    assert plan_role != apply_role, "plan and apply share one AWS role"
    assert "AWS_TERRAFORM_PLAN_ROLE_ARN" in plan_role
    assert "AWS_TERRAFORM_APPLY_ROLE_ARN" in apply_role


def test_every_piped_terraform_command_enforces_pipe_failure():
    """`cmd | tee` without pipefail reports tee's exit status: a false green."""
    offenders = []
    for name in _workflow_names():
        for job_name, step_name, run in _all_run_blocks(_workflow_yaml(name)):
            if _enables_pipefail(run):
                continue
            for line in _logical_lines(run):
                if "terraform" in line and _is_piped(line):
                    offenders.append(f"{name}:{job_name}:{step_name}: {line.strip()[:70]}")
    assert offenders == [], "piped terraform without pipefail: " + "; ".join(offenders)


def test_terraform_workflow_run_blocks_enable_strict_bash():
    """GitHub's default shell is `bash -e {0}`: no -u, and no pipefail."""
    offenders = []
    for name in STRICT_BASH_WORKFLOWS:
        for job_name, step_name, run in _all_run_blocks(_workflow_yaml(name)):
            body = [ln for ln in run.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            if len(body) < 2:
                continue  # single command: bash -e already fails the step
            if body[0].strip() != "set -euo pipefail":
                offenders.append(f"{name}:{job_name}:{step_name}")
    assert offenders == [], "multi-line run blocks without `set -euo pipefail`: " + ", ".join(
        offenders
    )


def test_strict_bash_scope_covers_every_workflow_that_touches_infrastructure():
    """Guards the scope of the test above.

    A hardcoded pair of workflow names left `deploy.yml` — the one workflow that
    mutates ECS on a push to main — outside the strict-bash control entirely.
    The covered set is therefore derived from what the workflows actually do.
    """
    touching = set()
    mutating = re.compile(
        r"\bterraform \b|\baws ecs\b|\baws application-autoscaling\b|\baws ssm\b"
    )
    for name in _workflow_names():
        for _job, _step, run in _all_run_blocks(_workflow_yaml(name)):
            if mutating.search(run):
                touching.add(name)
    uncovered = touching - set(STRICT_BASH_WORKFLOWS) - set(STRICT_BASH_ELSEWHERE)
    assert uncovered == set(), (
        "workflow(s) run terraform/AWS mutations but no strict-bash test covers "
        f"them: {sorted(uncovered)}"
    )
    # Neither list may drift into naming a workflow that does not exist.
    for name in STRICT_BASH_WORKFLOWS + STRICT_BASH_ELSEWHERE:
        assert (WORKFLOW_DIR / name).exists(), f"strict-bash list names a missing {name}"


def test_infrastructure_credential_probe_survives_unset_secrets_under_set_u():
    """`${!name}` aborts under `set -u`; the probe must use `${!name-}`."""
    doc = _workflow_yaml("infrastructure.yml")
    probe = _job_script(doc, "remote-plan-readiness")
    assert "set -euo pipefail" in probe
    assert '[ -z "${!name-}" ]' in probe
    assert '"${!name}"' not in probe


def test_infrastructure_checksums_its_configuration_plan_artifacts():
    doc = _workflow_yaml("infrastructure.yml")
    plan_script = _job_script(doc, "plan")
    assert 'sha256sum "plan-${PROFILE}.txt" > "plan-${PROFILE}.txt.sha256"' in plan_script
    uploads = [
        s for s in _steps(doc, "plan") if str(s.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert len(uploads) == 1
    paths = uploads[0]["with"]["path"]
    assert "plan-${{ matrix.profile }}.txt" in paths
    assert "plan-${{ matrix.profile }}.txt.sha256" in paths
    assert uploads[0]["with"]["if-no-files-found"] == "error"


def test_infrastructure_remote_plan_validates_plan_json_for_policy_and_cost():
    doc = _workflow_yaml("infrastructure.yml")
    steps = _steps(doc, "remote-plan")
    remote_plan = _job_script(doc, "remote-plan")
    # A machine-readable plan must exist for the validators to read — produced
    # under a never-uploaded raw name and sanitised into the published one,
    # because `terraform show -json` does not redact sensitive root variables.
    assert 'terraform show -json "tfplan-${PROFILE}" > plan-raw.json' in remote_plan
    assert SANITISER in remote_plan
    assert 'plan-raw.json "remote-plan-${PROFILE}.json"' in remote_plan
    assert "rm -f plan-raw.json" in remote_plan

    validating = [
        s
        for s in steps
        if s.get("run") and "scripts/release/check_terraform_plan_policy.py" in s["run"]
    ]
    assert len(validating) == 1, "plan-policy validation must be exactly one required step"
    step = validating[0]
    run = step["run"]
    assert "scripts/release/check_cost_model.py" in run
    # The policy validator reads the plan JSON and emits the canonical
    # inventory; the cost model scores that inventory. Both are profile-scoped.
    policy = run.split("check_terraform_plan_policy.py", 1)[1].split("python", 1)[0]
    assert '--profile "${PROFILE}"' in policy
    assert '--plan-json "${plan_json}"' in policy
    assert "test -s artifacts/profile-resource-inventory.json" in run
    cost = run.split("check_cost_model.py", 1)[1]
    assert '--profile "${PROFILE}"' in cost
    assert "--inventory artifacts/profile-resource-inventory.json" in cost
    # The cost model only applies where a budget is declared, and that decision
    # is read from the canonical policy data rather than hardcoded here.
    assert "config/deployment_profiles.yaml" in run
    assert "'budget'" in run
    # A non-zero exit has to fail the job.
    assert step.get("continue-on-error") in (None, False)
    assert "|| true" not in run and "|| echo" not in run and "set +e" not in run
    assert _enables_pipefail(run)

    uploads = [
        s
        for s in steps
        if str(s.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert len(uploads) == 1
    paths = uploads[0]["with"]["path"]
    for retained in (
        "remote-plan-${{ matrix.profile }}.json",
        "artifacts/profile-resource-inventory.json",
        "artifacts/plan-policy-report-${{ matrix.profile }}.txt",
        "artifacts/cost-model-report-${{ matrix.profile }}.txt",
    ):
        assert retained in paths, f"remote-plan evidence drops {retained}"


def test_infrastructure_remote_plan_rejects_a_stale_backend_digest_on_main():
    doc = _workflow_yaml("infrastructure.yml")
    validation = next(
        step for step in _steps(doc, "remote-plan")
        if step.get("name") == "Validate approved backend digest is present and current"
    )
    script = validation["run"]
    assert "aws ecr describe-images" in script
    assert "--image-ids imageDigest=\"$APPROVED_BACKEND_DIGEST\"" in script
    assert "--image-ids imageTag=\"$EXPECTED_COMMIT_SHA\"" in script
    assert '"$GITHUB_EVENT_NAME" = push' not in script
    assert '"$GITHUB_REF" = refs/heads/main' not in script
    assert "TF_BACKEND_IMAGE_DIGEST is stale" not in script
    assert "EXPECTED_COMMIT_SHA" in script


def test_infrastructure_requires_explicit_credentialed_remote_plan_dispatch():
    doc = _workflow_yaml("infrastructure.yml")
    remote_plan = doc["jobs"]["remote-plan"]
    assert remote_plan["if"] == "github.event_name == 'workflow_dispatch' && needs.remote-plan-readiness.outputs.configured == 'true'"

    gate = doc["jobs"]["require-production-credentials"]
    assert set(gate["needs"]) == {"remote-plan-readiness", "plan", "remote-plan"}
    assert gate["if"] == "always() && github.event_name == 'workflow_dispatch'"
    script = _job_script(doc, "require-production-credentials")
    for guarded in ('"$CONFIGURED" != \'true\'', '"$PLAN_RESULT" != \'success\'',
                    '"$REMOTE_PLAN_RESULT" != \'success\''):
        assert guarded in script, f"promotability gate no longer checks {guarded}"
    assert script.count("exit 1") == 4


def test_promotion_cannot_proceed_when_remote_plan_credentials_are_missing():
    """The credential set that gates remote plans also gates reviewed plans."""
    infra = _workflow_yaml("infrastructure.yml")
    probe_step = next(
        s for s in _steps(infra, "remote-plan-readiness") if s.get("id") == "credentials"
    )
    shared = {
        name
        for name in probe_step["env"]
        if name not in {
            "AWS_INFRA_ROLE_ARN",
            "BACKEND_IMAGE_DIGEST",
            "EXPECTED_COMMIT_SHA",
            "TF_ML_IMAGE_DIGEST",
        }
    }
    assert len(shared) == 12
    assert "AWS_TERRAFORM_PLAN_ROLE_ARN" in shared
    assert "TF_AMPLIFY_GITHUB_ACCESS_TOKEN" in probe_step["env"]
    assert "TF_AMPLIFY_GITHUB_ACCESS_TOKEN \\\n" in probe_step["run"]

    promote = _workflow_yaml(APPLY_WORKFLOW)
    guard = next(
        s
        for s in _steps(promote, "plan")
        if s.get("run") and "AWS_TERRAFORM_PLAN_ROLE_ARN" in s["run"] and "missing" in s["run"]
    )
    assert shared <= set(guard["env"]), (
        "the reviewed-plan credential guard does not cover the remote-plan credential set"
    )
    assert "AWS_TERRAFORM_PLAN_ROLE_ARN" in guard["env"]
    assert '[ -z "${!name-}" ]' in guard["run"]
    assert "exit 1" in guard["run"]
    # Plan-only promotion must remain runnable without mutation credentials;
    # apply enforces its apply-role requirement in the protected apply job.
    assert "AWS_TERRAFORM_APPLY_ROLE_ARN \\\n" not in guard["run"]
    assert guard["run"].count("AWS_TERRAFORM_APPLY_ROLE_ARN") == 2
    assert '"${{ inputs.action }}" = "apply"' in guard["run"]
    assert "gh api" not in guard["run"]
    assert "TF_VAR_amplify_github_access_token" in guard["run"]
    assert "TF_AMPLIFY_GITHUB_ACCESS_TOKEN \\\n" in guard["run"]
    # The guard runs before any AWS credential is assumed or plan is produced.
    names = [s.get("name", "") for s in _steps(promote, "plan")]
    uses = [str(s.get("uses", "")) for s in _steps(promote, "plan")]
    guard_index = _steps(promote, "plan").index(guard)
    aws_index = next(i for i, u in enumerate(uses) if u.startswith("aws-actions/"))
    plan_index = next(i for i, n in enumerate(names) if n == "Create immutable reviewed plan")
    assert guard_index < aws_index < plan_index


def test_remote_plan_requires_ml_digest_only_for_dedicated_ml_profiles():
    """Inline-ML profiles must not be blocked by an unrelated ML image secret."""
    infra = _workflow_yaml("infrastructure.yml")
    probe = next(
        s for s in _steps(infra, "remote-plan-readiness") if s.get("id") == "credentials"
    )
    assert "TF_ML_IMAGE_DIGEST" not in probe["env"]
    required_names = probe["run"].split("for name in", 1)[1].split("do", 1)[0]
    assert "TF_ML_IMAGE_DIGEST" not in required_names

    remote_plan = _job_script(infra, "remote-plan")
    assert '"$PROFILE" == production-scale || "$PROFILE" == enterprise-isolated' in remote_plan
    assert "requires TF_ML_IMAGE_DIGEST" in remote_plan
    assert "^sha256:[0-9a-f]{64}$" in remote_plan


def test_amplify_checkout_token_is_required_for_public_and_private_repositories():
    """Amplify requires a real repository token regardless of visibility."""
    infra = _workflow_yaml("infrastructure.yml")
    readiness = _steps(infra, "remote-plan-readiness")
    probe = next(step for step in readiness if step.get("id") == "credentials")
    assert "TF_AMPLIFY_GITHUB_ACCESS_TOKEN" in probe["run"]
    assert "amplify_token" in probe["run"]
    remote_plan = _steps(infra, "remote-plan")
    validate = next(step for step in remote_plan if step.get("name") == "Validate Amplify checkout token")
    assert "AWS Amplify requires one for public and private repositories" in validate["run"]
    assert "TF_VAR_amplify_github_access_token" in validate["run"]
    assert "TF_VAR_amplify_github_access_token" not in infra["jobs"]["remote-plan"]["env"]


# ---------------------------------------------------------------------------
# Reviewed promotion: plan provenance is recorded, and apply verifies all of it
# ---------------------------------------------------------------------------


PLAN_EVIDENCE = {
    "reviewed.tfplan.sha256": "sha256sum reviewed.tfplan > reviewed.tfplan.sha256",
    "reviewed.commit": 'printf \'%s\\n\' "$COMMIT_SHA" > reviewed.commit',
    "reviewed.profile": 'printf \'%s\\n\' "$PROFILE" > reviewed.profile',
    "reviewed.deployment-lane": 'printf \'%s\\n\' "${DEPLOYMENT_LANE}" > reviewed.deployment-lane',
    "reviewed.state-key": (
        'printf \'%s\\n\' "profiles/${PROFILE}/terraform.tfstate" > reviewed.state-key'
    ),
    "reviewed.state-bucket": 'printf \'%s\\n\' "$TF_STATE_BUCKET" > reviewed.state-bucket',
    "reviewed.state-lock-table": 'printf \'%s\\n\' "$TF_LOCK_TABLE" > reviewed.state-lock-table',
    "reviewed.terraform-version": (
        "terraform version -json | jq -r '.terraform_version' > reviewed.terraform-version"
    ),
    "reviewed.lock.sha256": (
        "sha256sum .terraform.lock.hcl | cut -d' ' -f1 > reviewed.lock.sha256"
    ),
    "reviewed.created-utc": "date -u +%Y-%m-%dT%H:%M:%SZ > reviewed.created-utc",
    "reviewed.expires-utc": "date -u -d '+24 hours' +%Y-%m-%dT%H:%M:%SZ > reviewed.expires-utc",
    "reviewed.staging-state": 'printf \'%s\\n\' "${STAGING_STATE}" > reviewed.staging-state',
}


def test_promotion_plan_records_the_full_plan_provenance():
    doc = _workflow_yaml(APPLY_WORKFLOW)
    plan_script = _job_script(doc, "plan")
    for field, statement in PLAN_EVIDENCE.items():
        assert statement in plan_script, f"the reviewed plan no longer records {field}"
    # The lockfile digest is taken from the checked-out tree, before init can
    # touch it, so apply can compare it against the same commit's git content.
    # Provider installation is routed through the shared retry/lockfile guard;
    # keep the provenance assertion tied to that wrapper rather than a raw init
    # command so transient registry failures cannot bypass verification.
    assert plan_script.index("sha256sum .terraform.lock.hcl") < plan_script.index(
        "terraform_init_retry.sh"
    )
    # Reports retained alongside the plan: the policy validator's canonical
    # inventory becomes the reviewed resource inventory.
    assert (
        'cp artifacts/profile-resource-inventory.json "${TF_DIR}/reviewed.resources.json"'
        in plan_script
    )
    assert 'tee "${TF_DIR}/reviewed.policy.txt"' in plan_script
    assert 'tee "${TF_DIR}/reviewed.cost.txt"' in plan_script
    assert '--inventory "${TF_DIR}/reviewed.resources.json"' in plan_script
    uploads = [
        s for s in _steps(doc, "plan") if str(s.get("uses", "")).startswith("actions/upload-artifact")
    ]
    # Two artifacts: reviewable evidence, and the secret-bearing binary plan.
    assert len(uploads) == 2, "the reviewed plan no longer separates its evidence from the binary plan"
    evidence, binary = uploads
    assert "reviewed.*" in evidence["with"]["path"]
    assert all(u["with"]["if-no-files-found"] == "error" for u in uploads)
    # Both artifacts must still be reachable through the single download pattern
    # the apply job and staging-lifecycle.yml use.
    for upload in uploads:
        assert upload["with"]["name"].startswith("terraform-plan-${{ inputs.profile }}-")


def test_promotion_apply_verifies_every_recorded_field_before_applying():
    doc = _workflow_yaml(APPLY_WORKFLOW)
    apply_script = _job_script(doc, "apply")
    apply_at = apply_script.index("terraform apply")
    checks = {
        "profile": 'test "$(cat reviewed.profile)" = "$PROFILE"',
        "reviewed commit": 'test "$(cat reviewed.commit)" = "$REVIEWED_COMMIT"',
        "checked-out commit": 'test "$(cat reviewed.commit)" = "$(git rev-parse HEAD)"',
        "state key": (
            'test "$(cat reviewed.state-key)" = "profiles/${PROFILE}/terraform.tfstate"'
        ),
        "state bucket": 'test "$reviewed_state_bucket" = "$TF_STATE_BUCKET"',
        "state lock table": 'test "$reviewed_state_lock_table" = "$TF_LOCK_TABLE"',
        "dispatch checksum": (
            'test "$(sha256sum reviewed.tfplan | cut -d\' \' -f1)" = "$PLAN_CHECKSUM"'
        ),
        "recorded checksum": "sha256sum --check --status reviewed.tfplan.sha256",
        "lockfile": (
            'test "$(cat reviewed.lock.sha256)" = "$(sha256sum .terraform.lock.hcl'
            " | cut -d' ' -f1)\""
        ),
        "terraform version": (
            'test "$(cat reviewed.terraform-version)" = "$(terraform version -json'
            " | jq -r '.terraform_version')\""
        ),
        "expiry": 'test "$(date -u +%s)" -lt "$(date -u -d "$(cat reviewed.expires-utc)" +%s)"',
    }
    for label, statement in checks.items():
        assert statement in apply_script, f"apply no longer verifies the {label}"
        assert apply_script.index(statement) < apply_at, f"{label} is verified after apply"
    # Every artefact the plan recorded is required to be present.
    for field in PLAN_EVIDENCE:
        assert field in apply_script, f"apply never inspects {field}"
    assert "reviewed.policy.txt" in apply_script
    assert "reviewed.cost.txt" in apply_script
    assert "reviewed.resources.json" in apply_script


def test_promotion_apply_refuses_an_expired_plan():
    doc = _workflow_yaml(APPLY_WORKFLOW)
    verify = next(s for s in _steps(doc, "apply") if s.get("id") == "reviewed")
    run = verify["run"]
    assert '"$now_epoch" -ge "$expires_epoch"' in run, "expired plans are not rejected"
    assert '"$expires_epoch" -le "$created_epoch"' in run, "a backdated expiry is not rejected"
    assert '"$((expires_epoch - created_epoch))" -gt 86400' in run, (
        "a plan may claim a validity window longer than 24 hours"
    )
    assert run.count("exit 1") >= 3
    # Expiry is re-checked at the apply itself, after any approval wait.
    assert "reviewed.expires-utc" in _job_script(doc, "apply").split("terraform apply")[0]


def test_promotion_apply_binds_to_the_reviewed_commit_not_the_dispatch_ref():
    doc = _workflow_yaml(APPLY_WORKFLOW)
    apply_job = doc["jobs"]["apply"]
    rendered = yaml.safe_dump(apply_job)
    # github.sha is the ref the APPLY was dispatched from; it says nothing
    # about the code the reviewed plan was built from.
    assert "github.sha" not in rendered, "apply is still bound to the dispatch ref"
    checkouts = [s for s in _steps(doc, "apply") if str(s.get("uses", "")).startswith("actions/checkout")]
    assert len(checkouts) == 1
    assert checkouts[0]["with"]["ref"] == "${{ steps.reviewed.outputs.commit }}"
    # The commit fed to checkout is validated as a sha before it is used.
    verify = next(s for s in _steps(doc, "apply") if s.get("id") == "reviewed")
    assert "^[0-9a-f]{40}$" in verify["run"]
    assert _steps(doc, "apply").index(verify) < _steps(doc, "apply").index(checkouts[0])
    # ...and the resulting checkout is proven to be that commit.
    apply_script = _job_script(doc, "apply")
    assert 'head_sha="$(git rev-parse HEAD)"' in apply_script
    assert '[ "$head_sha" != "$REVIEWED_COMMIT" ]' in apply_script
    # Terraform itself is pinned to the version that produced the plan.
    setup = next(s for s in _steps(doc, "apply") if str(s.get("uses", "")).startswith("hashicorp/setup-terraform"))
    assert setup["with"]["terraform_version"] == "${{ steps.reviewed.outputs.terraform_version }}"


def test_promotion_uses_per_profile_terraform_environments():
    doc = _workflow_yaml(APPLY_WORKFLOW)
    environment = doc["jobs"]["apply"]["environment"]
    name = environment["name"] if isinstance(environment, dict) else environment
    assert "production-terraform" not in name, "the shared production environment is back"
    expected = {
        "staging": "staging-terraform",
        "production-lean": "production-lean-terraform",
        "production-scale": "production-scale-terraform",
        "enterprise-isolated": "enterprise-terraform",
        "demo": "demo-terraform",
        "preview": "preview-terraform",
    }
    for profile, env_name in expected.items():
        assert f"inputs.profile == '{profile}' && '{env_name}'" in name, (
            f"profile {profile} is not mapped to {env_name}"
        )
    # Every dispatchable profile is covered by the mapping.
    on = doc.get("on", doc.get(True))
    options = on["workflow_dispatch"]["inputs"]["profile"]["options"]
    assert set(options) == set(expected) == set(TF_PROFILES)
    # The plan job must not claim any deployment environment: only apply is
    # allowed to sit behind reviewers.
    assert "environment" not in doc["jobs"]["plan"]


# ---------------------------------------------------------------------------
# Secret exposure: `terraform show -json` does NOT redact sensitive root
# variables, and both plan workflows publish that JSON as a build artifact.
# ---------------------------------------------------------------------------


CANARY = "SUPERSECRET_CANARY_VALUE"


def _plan_with_secret(secret: str = CANARY) -> dict:
    """A minimal `terraform show -json` document shaped like the real one.

    `variables` carries the secret exactly the way Terraform emits it: verbatim,
    with no redaction and no sensitivity marker of any kind.
    """
    return {
        "format_version": "1.2",
        "terraform_version": "1.7.5",
        "variables": {
            "environment": {"value": "staging"},
            "network_egress_mode": {"value": "vpc_endpoints"},
            "auth0_management_client_secret": {"value": secret},
            "auth0_management_client_id": {"value": "m2m-client-id"},
        },
        "planned_values": {
            "root_module": {
                "resources": [
                    {
                        "address": "aws_ssm_parameter.auth0",
                        "type": "aws_ssm_parameter",
                        "name": "auth0",
                        "values": {"name": "/auth0/secret", "value": secret},
                        "sensitive_values": {"value": True},
                    }
                ],
                "child_modules": [
                    {
                        "address": "module.auth0",
                        "resources": [
                            {
                                "address": "module.auth0.auth0_client.aether",
                                "type": "auth0_client",
                                "name": "aether",
                                "values": {"name": "aether", "client_secret": secret},
                                "sensitive_values": {"client_secret": True},
                            }
                        ],
                    }
                ],
            }
        },
        "resource_changes": [
            {
                "address": "aws_ssm_parameter.auth0",
                "type": "aws_ssm_parameter",
                "name": "auth0",
                "mode": "managed",
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": {"name": "/auth0/secret", "value": secret},
                    "after_sensitive": {"value": True},
                },
            }
        ],
        "configuration": {
            "root_module": {
                "variables": {
                    "environment": {"default": "staging"},
                    "network_egress_mode": {"default": "vpc_endpoints"},
                    "auth0_management_client_secret": {"sensitive": True},
                    "auth0_management_client_id": {"sensitive": True},
                }
            }
        },
        "prior_state": {"values": {"root_module": {"resources": [
            {"address": "aws_ssm_parameter.auth0", "values": {"value": secret}}
        ]}}},
    }


def test_the_sanitiser_removes_a_sensitive_root_variable_value():
    """The exact leak: a `sensitive = true` variable's value in the plan JSON."""
    clean = _sanitiser().sanitize(_plan_with_secret(), environ={})
    assert CANARY not in json.dumps(clean), "the sensitive variable value survived"
    # The variable is still NAMED, so a reviewer can see what was supplied.
    assert "auth0_management_client_secret" in clean["variables"]
    assert clean["variables"]["auth0_management_client_secret"]["value"] != CANARY


def test_the_sanitiser_keeps_exactly_what_the_policy_gate_reads():
    """check_terraform_plan_policy.py reads two variable values; keep those."""
    clean = _sanitiser().sanitize(_plan_with_secret(), environ={})
    assert clean["variables"]["environment"]["value"] == "staging"
    assert clean["variables"]["network_egress_mode"]["value"] == "vpc_endpoints"
    for key in ("format_version", "terraform_version", "planned_values",
                "resource_changes", "configuration"):
        assert key in clean, f"the sanitised plan lost {key}"
    # Non-consumed top-level state that can only carry more values is dropped.
    assert "prior_state" not in clean
    # The resources the gate counts survive intact.
    root = clean["planned_values"]["root_module"]
    assert root["resources"][0]["values"]["name"] == "/auth0/secret"
    assert clean["resource_changes"][0]["change"]["actions"] == ["create"]


def test_the_variable_allow_list_is_exactly_what_the_policy_gate_reads():
    """Derived from the consumer, so it cannot quietly widen.

    Widening the allow-list is how the leak comes back: it is the one layer that
    works without Terraform having told us which variables are sensitive.
    """
    policy = (ROOT / "scripts/release/check_terraform_plan_policy.py").read_text(
        encoding="utf-8"
    )
    consumed = set(re.findall(r'\(plan\.get\("variables"\) or \{\}\)\.get\("(\w+)"\)', policy))
    assert consumed, "the policy gate no longer reads plan variables the way this test detects"
    assert set(_sanitiser().KEEP_VARIABLE_VALUES) == consumed, (
        "the sanitiser's variable allow-list no longer matches what "
        f"check_terraform_plan_policy.py actually reads ({sorted(consumed)})"
    )


def test_the_allow_list_holds_even_when_terraform_declares_no_sensitivity():
    """The allow-list is an independent layer, not a helper for the literal scrub.

    With no `sensitive` flag in `configuration` and no `TF_VAR_*` in the
    environment, nothing can identify the secret by value — the allow-list is
    all that stands between it and the artifact, so it must stand alone.
    """
    plan = _plan_with_secret()
    plan["configuration"]["root_module"]["variables"] = {}
    clean = _sanitiser().sanitize(plan, environ={})
    assert clean["variables"]["auth0_management_client_secret"]["value"] != CANARY
    assert clean["variables"]["auth0_management_client_id"]["value"] != CANARY
    assert CANARY not in json.dumps(clean["variables"])


def test_the_sanitiser_scrubs_secret_values_out_of_resources_too():
    """A secret copied into a resource argument is still a secret."""
    clean = _sanitiser().sanitize(_plan_with_secret(), environ={})
    blob = json.dumps(clean)
    assert CANARY not in blob
    child = clean["planned_values"]["root_module"]["child_modules"][0]
    assert child["resources"][0]["values"]["client_secret"] != CANARY
    assert clean["resource_changes"][0]["change"]["after"]["value"] != CANARY


def test_the_sanitiser_scrubs_embedded_and_url_encoded_secret_values():
    """Provider-expanded strings cannot carry a sensitive token through."""
    token = "ghp_CANARY+/value"
    plan = _plan_with_secret(token)
    plan["planned_values"]["root_module"]["resources"][0]["values"] = {
        "name": "/amplify/app",
        "connection": f"https://example.invalid/{token}/checkout",
        "encoded": "https%3a%2f%2fexample.invalid%2fghp_CANARY%2b%2fvalue",
    }
    plan["configuration"]["root_module"]["variables"] = {
        "amplify_github_access_token": {"sensitive": True},
    }
    plan["variables"] = {
        "amplify_github_access_token": {"value": token},
    }

    clean = _sanitiser().sanitize(plan, environ={})
    blob = json.dumps(clean)
    assert token not in blob
    assert "ghp_CANARY%2b%2fvalue" not in blob
    assert "__REDACTED_SENSITIVE__" in blob


def test_the_sanitiser_scrubs_embedded_secret_values_supplied_by_environment():
    """The hosted TF_VAR path is protected even when the plan omits the value."""
    token = "ghp_ENV_CANARY+/value"
    plan = _plan_with_secret()
    plan["variables"] = {}
    plan["configuration"]["root_module"]["variables"] = {
        "amplify_github_access_token": {"sensitive": True},
    }
    plan["planned_values"]["root_module"]["resources"][0]["values"] = {
        "connection": "https://example.invalid/ghp_ENV_CANARY%2b%2fvalue/checkout",
    }

    clean = _sanitiser().sanitize(
        plan, environ={"TF_VAR_amplify_github_access_token": token}
    )
    assert token not in json.dumps(clean)
    assert "ghp_ENV_CANARY%2b%2fvalue" not in json.dumps(clean)


def test_the_sanitiser_scrubs_provider_derived_credential_attributes():
    """Credential-shaped provider output is redacted without literal matching."""
    token = "provider-token-" + "CANARY+/value"
    plan = _plan_with_secret(token)
    plan["configuration"]["root_module"]["variables"] = {
        "amplify_github_access_token": {"sensitive": True},
    }
    plan["variables"] = {
        "amplify_github_access_token": {"value": token},
    }
    transformed = "provider-derived-token-that-is-not-the-root-value"
    planned_resource = {
        "address": "aws_amplify_app.marketing",
        "type": "aws_amplify_app",
        "name": "marketing",
        "values": {"access_token": transformed},
        # Simulate a provider that failed to carry the mask into its output.
        "sensitive_values": {"access_token": False},
    }
    plan["planned_values"]["root_module"]["resources"] = [planned_resource]
    plan["resource_changes"] = [{
        "address": "aws_amplify_app.marketing",
        "type": "aws_amplify_app",
        "name": "marketing",
        "mode": "managed",
        "change": {
            "actions": ["create"],
            "before": None,
            "after": {"access_token": transformed},
            "after_sensitive": {"access_token": False},
        },
    }]

    clean = _sanitiser().sanitize(plan, environ={})
    assert clean["planned_values"]["root_module"]["resources"][0]["values"]["access_token"] == (
        "__REDACTED_SENSITIVE__"
    )
    assert clean["resource_changes"][0]["change"]["after"]["access_token"] == (
        "__REDACTED_SENSITIVE__"
    )


def test_the_sanitiser_also_scrubs_the_value_supplied_through_the_environment():
    """The plan is produced from TF_VAR_*; that value must not survive either."""
    plan = _plan_with_secret()
    # Terraform emitted a different rendering, but the env still holds the secret.
    plan["planned_values"]["root_module"]["resources"][0]["values"] = {
        "name": "/auth0/secret", "value": CANARY, "sensitive_values": None,
    }
    plan["planned_values"]["root_module"]["resources"][0].pop("sensitive_values")
    clean = _sanitiser().sanitize(
        plan, environ={"TF_VAR_auth0_management_client_secret": CANARY}
    )
    assert CANARY not in json.dumps(clean)


def test_the_sanitiser_fails_closed_rather_than_writing_a_leaky_plan():
    """A surviving secret must stop the job, not ship in an artifact.

    The scrubbers rewrite string VALUES. A secret that Terraform emitted as a
    map KEY survives every structural pass, which is exactly the class of gap
    the final re-scan exists to catch — so it must raise, not write.
    """
    plan = _plan_with_secret()
    plan["planned_values"]["root_module"]["resources"][0]["values"]["tags"] = {
        CANARY: "leaked-through-a-key"
    }
    raised = False
    try:
        _sanitiser().sanitize(plan, environ={})
    except SystemExit as exc:
        raised = True
        assert "still carries a sensitive" in str(exc)
        assert "planned_values.root_module.resources" in str(exc)
    assert raised, "sanitisation returned a document that still holds the secret"


def test_the_sanitiser_is_runnable_as_the_workflows_invoke_it(tmp_path):
    source = tmp_path / "plan-raw.json"
    destination = tmp_path / "plan.json"
    source.write_text(json.dumps(_plan_with_secret()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / SANITISER), str(source), str(destination)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert CANARY not in destination.read_text(encoding="utf-8")


def test_sanitising_a_real_plan_does_not_change_the_policy_verdict(tmp_path):
    """Redaction must not become a way to slip a plan past the gate.

    Run check_terraform_plan_policy.py over real fixture plans before and after
    sanitisation and require identical per-check verdicts — on plans that PASS
    and on plans that FAIL, so a weakened gate shows up as a fixture that stops
    failing.
    """
    policy = ROOT / "scripts/release/check_terraform_plan_policy.py"
    fixtures = ROOT / "tests/fixtures/terraform_plans"
    cases = [
        ("staging", "staging-awake.json"),
        ("staging", "staging-asleep.json"),
        ("production-lean", "production-lean-valid.json"),
        ("production-lean", "production-lean-nat-gateway.json"),
        ("production-lean", "production-lean-dedicated-ml.json"),
    ]
    for profile, fixture in cases:
        source = fixtures / fixture
        if not source.exists():  # pragma: no cover - fixture set may evolve
            continue
        clean = tmp_path / f"clean-{fixture}"
        assert subprocess.run(
            [sys.executable, str(ROOT / SANITISER), str(source), str(clean)],
            capture_output=True, text=True,
        ).returncode == 0

        def verdict(plan: Path, out: Path) -> tuple[int, list]:
            code = subprocess.run(
                [sys.executable, str(policy), "--profile", profile,
                 "--plan-json", str(plan), "--out-dir", str(out)],
                capture_output=True, text=True, cwd=ROOT,
            ).returncode
            result = json.loads((out / "profile-policy-result.json").read_text())
            return code, [(r["check"], r["status"]) for r in result["results"]]

        raw_code, raw_checks = verdict(source, tmp_path / f"raw-{fixture}")
        clean_code, clean_checks = verdict(clean, tmp_path / f"san-{fixture}")
        assert (raw_code, raw_checks) == (clean_code, clean_checks), (
            f"sanitising {fixture} changed the {profile} policy verdict"
        )
        assert raw_checks, f"{fixture} produced no checks at all"


def test_no_workflow_publishes_unsanitised_terraform_plan_json():
    """Every `terraform show -json` must reach an artifact through the sanitiser.

    The raw document is written under a name the upload globs do not match, and
    deleted; the published name is only ever produced by the sanitiser.
    """
    offenders = []
    for name in _workflow_names():
        for job_name, step_name, run in _all_run_blocks(_workflow_yaml(name)):
            if "terraform show -json" not in run:
                continue
            where = f"{name}:{job_name}:{step_name}"
            if SANITISER not in run:
                offenders.append(f"{where} writes plan JSON without the sanitiser")
                continue
            for line in _logical_lines(run):
                if "terraform show -json" not in line or line.strip().startswith("#"):
                    continue
                target = line.rsplit(">", 1)[-1].strip().strip('"')
                assert target in ("plan-raw.json", '"plan-raw.json"'), (
                    f"{where}: `terraform show -json` writes straight to {target}; "
                    "it must land on the never-uploaded raw name first"
                )
            assert "rm -f plan-raw.json" in run, f"{where} leaves the raw plan on disk"
    assert offenders == [], "; ".join(offenders)


def test_both_plan_workflows_route_their_plan_json_through_the_sanitiser():
    """Named explicitly: these are the two workflows that upload plan JSON."""
    promote = _job_script(_workflow_yaml(APPLY_WORKFLOW), "plan")
    assert SANITISER in promote
    assert "plan-raw.json reviewed.tfplan.json" in promote
    infra = _job_script(_workflow_yaml("infrastructure.yml"), "remote-plan")
    assert SANITISER in infra
    assert 'plan-raw.json "remote-plan-${PROFILE}.json"' in infra
    # The sanitiser runs before anything reads or ships the plan JSON.
    assert promote.index(SANITISER) < promote.index("check_terraform_plan_policy.py")
    assert infra.index(SANITISER) < infra.index("check_terraform_plan_policy.py")


def test_the_binary_plan_is_treated_as_a_secret_bearing_artifact():
    """It embeds every root variable value and cannot be sanitised."""
    doc = _workflow_yaml(APPLY_WORKFLOW)
    uploads = [
        s for s in _steps(doc, "plan")
        if str(s.get("uses", "")).startswith("actions/upload-artifact")
    ]
    binary_path = "deploy/aws/terraform/reviewed.tfplan"
    evidence = [u for u in uploads if "reviewed.*" in u["with"]["path"]]
    binary = [u for u in uploads if u["with"]["path"].strip() == binary_path]
    assert len(evidence) == 1 and len(binary) == 1, (
        "the binary plan is not uploaded separately from the reviewable evidence"
    )
    # The long-lived evidence artifact must NOT contain the binary plan.
    assert "!deploy/aws/terraform/reviewed.tfplan" in evidence[0]["with"]["path"]
    # A reviewed plan is only legal to apply for 24h, so one day is the whole
    # window the apply path can use.
    assert int(binary[0]["with"]["retention-days"]) == 1, (
        "the secret-bearing binary plan outlives the 24h window it can be applied in"
    )
    assert int(evidence[0]["with"]["retention-days"]) > 1
    # ...and the risk is stated where a maintainer will read it.
    workflow = _workflow(APPLY_WORKFLOW)
    assert "SECRET-BEARING ARTIFACT" in workflow
    assert "sensitive = true" in workflow


def test_the_apply_verifies_the_plan_run_is_a_run_of_this_workflow():
    """The artifact-name pattern constrains the name, not the producer."""
    doc = _workflow_yaml(APPLY_WORKFLOW)
    steps = _steps(doc, "apply")
    verify = next(
        s for s in steps
        if s.get("run") and "actions/runs/${PLAN_RUN_ID}" in s["run"]
    )
    run = verify["run"]
    assert "'.github/workflows/terraform-promote.yml'" in run, (
        "the apply does not bind plan_run_id to this workflow file"
    )
    assert "not the reviewed promotion workflow" in run
    assert 'concluded ${run_conclusion}, not success' in run
    assert run.count("exit 1") >= 2
    assert verify["env"]["PLAN_RUN_ID"] == "${{ inputs.plan_run_id }}"
    # It runs BEFORE a single byte of that run's output is downloaded.
    download = next(
        i for i, s in enumerate(steps)
        if str(s.get("uses", "")).startswith("actions/download-artifact")
    )
    assert steps.index(verify) < download
    # The job can actually read run metadata.
    assert doc["jobs"]["apply"]["permissions"]["actions"] == "read"


def test_the_recorded_staging_state_is_load_bearing_in_the_apply():
    """A file that is written and never read is not a control."""
    doc = _workflow_yaml(APPLY_WORKFLOW)
    plan_script = _job_script(doc, "plan")
    assert "> reviewed.staging-state" in plan_script
    verify = next(s for s in _steps(doc, "apply") if s.get("id") == "reviewed")
    run = verify["run"]
    assert "reviewed.staging-state" in run, "the apply never reads the recorded shape"
    assert "awake|asleep)" in run, "any string passes as a reviewed staging_state"
    assert "not awake or asleep" in run
    # The required-evidence loop lists it, so an artifact missing it is refused.
    required = run.split("for artefact in", 1)[1].split("do", 1)[0]
    assert "reviewed.staging-state" in required
