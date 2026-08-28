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


def test_native_sdk_validation_runs_on_pull_requests():
    workflow = _workflow("sdk-release-validation.yml")
    assert "github.event_name == 'push'" not in workflow
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


def test_deploy_builds_each_spa_with_its_own_auth0_client_and_endpoints():
    workflow = _workflow("deploy.yml")
    assert "secrets.AETHER_AUTH0_CLIENT_ID" in workflow
    assert "secrets.KYBER_AUTH0_CLIENT_ID" in workflow
    assert "vars.KYBER_API_BASE_URL" in workflow
    assert "vars.KYBER_WS_BASE_URL" in workflow
    kyber_build = workflow.split("npm --workspace frontend/kyber run build")[0]
    assert 'VITE_AUTH0_CLIENT_ID="$KYBER_AUTH0_CLIENT_ID"' in kyber_build
    assert 'VITE_API_BASE_URL="$KYBER_API_BASE_URL"' in kyber_build
    assert 'VITE_WS_BASE_URL="$KYBER_WS_BASE_URL"' in kyber_build


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
    """A credential-less push to main must go green with a loud not-armed
    notice — never fail the run — and the enforce step must run fail-closed
    only when the complete credential set is present. A failed probe publishes
    no output and must not be misattributed to missing credentials, so the
    notice also requires the probe job to have succeeded."""
    doc = _workflow_yaml("infrastructure.yml")
    steps = doc["jobs"]["require-production-credentials"]["steps"]

    not_armed = next(
        s for s in steps if "not armed" in s.get("name", "").lower()
    )
    assert "needs.remote-plan-readiness.result == 'success'" in not_armed["if"]
    assert "needs.remote-plan-readiness.outputs.configured != 'true'" in not_armed["if"]
    assert "NOT promotable" in not_armed["run"]
    assert "NO-OP" in not_armed["run"]

    enforce = next(
        s for s in steps if s.get("name") == "Enforce credentialed remote plans"
    )
    assert "needs.remote-plan-readiness.outputs.configured == 'true'" in enforce["if"]
    # The enforce step still carries all three fail-closed checks.
    assert enforce["run"].count("exit 1") == 3


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
    versions = (ROOT / "AWS Deployment/aether-aws/terraform/versions.tf").read_text(
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
    variables = (ROOT / "AWS Deployment/aether-aws/terraform/variables.tf").read_text(
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


def test_infrastructure_requires_credentialed_remote_plans_on_pushes_to_main():
    doc = _workflow_yaml("infrastructure.yml")
    remote_plan = doc["jobs"]["remote-plan"]
    assert remote_plan["if"] == "needs.remote-plan-readiness.outputs.configured == 'true'"

    gate = doc["jobs"]["require-production-credentials"]
    assert set(gate["needs"]) == {"remote-plan-readiness", "plan", "remote-plan"}
    assert "github.event_name == 'push'" in gate["if"]
    assert "github.ref == 'refs/heads/main'" in gate["if"]
    script = _job_script(doc, "require-production-credentials")
    for guarded in ('"$CONFIGURED" != \'true\'', '"$PLAN_RESULT" != \'success\'',
                    '"$REMOTE_PLAN_RESULT" != \'success\''):
        assert guarded in script, f"promotability gate no longer checks {guarded}"
    assert script.count("exit 1") == 3


def test_promotion_cannot_proceed_when_remote_plan_credentials_are_missing():
    """The credential set that gates remote plans also gates reviewed plans."""
    infra = _workflow_yaml("infrastructure.yml")
    probe_step = next(
        s for s in _steps(infra, "remote-plan-readiness") if s.get("id") == "credentials"
    )
    shared = {
        name
        for name in probe_step["env"]
        if name not in {"AWS_INFRA_ROLE_ARN", "TF_BACKEND_IMAGE_DIGEST", "TF_ML_IMAGE_DIGEST"}
    }
    assert len(shared) == 10

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
    # The guard runs before any AWS credential is assumed or plan is produced.
    names = [s.get("name", "") for s in _steps(promote, "plan")]
    uses = [str(s.get("uses", "")) for s in _steps(promote, "plan")]
    guard_index = _steps(promote, "plan").index(guard)
    aws_index = next(i for i, u in enumerate(uses) if u.startswith("aws-actions/"))
    plan_index = next(i for i, n in enumerate(names) if n == "Create immutable reviewed plan")
    assert guard_index < aws_index < plan_index


# ---------------------------------------------------------------------------
# Reviewed promotion: plan provenance is recorded, and apply verifies all of it
# ---------------------------------------------------------------------------


PLAN_EVIDENCE = {
    "reviewed.tfplan.sha256": "sha256sum reviewed.tfplan > reviewed.tfplan.sha256",
    "reviewed.commit": 'printf \'%s\\n\' "$COMMIT_SHA" > reviewed.commit',
    "reviewed.profile": 'printf \'%s\\n\' "$PROFILE" > reviewed.profile',
    "reviewed.state-key": (
        'printf \'%s\\n\' "profiles/${PROFILE}/terraform.tfstate" > reviewed.state-key'
    ),
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
    binary_path = "AWS Deployment/aether-aws/terraform/reviewed.tfplan"
    evidence = [u for u in uploads if "reviewed.*" in u["with"]["path"]]
    binary = [u for u in uploads if u["with"]["path"].strip() == binary_path]
    assert len(evidence) == 1 and len(binary) == 1, (
        "the binary plan is not uploaded separately from the reviewable evidence"
    )
    # The long-lived evidence artifact must NOT contain the binary plan.
    assert "!AWS Deployment/aether-aws/terraform/reviewed.tfplan" in evidence[0]["with"]["path"]
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
