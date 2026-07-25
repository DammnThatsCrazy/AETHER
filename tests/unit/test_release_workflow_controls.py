"""Release workflows must validate pull requests without mutating them."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

# The only workflow permitted to run `terraform apply`.
APPLY_WORKFLOW = "terraform-promote.yml"
TF_PROFILES = ("staging", "production-lean", "production-scale", "enterprise-isolated")
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
    assert workflow.count('-backend-config="bucket=${TF_STATE_BUCKET}"') == 2
    assert workflow.count('-backend-config="key=profiles/${PROFILE}/terraform.tfstate"') == 2
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
    appliers = set()
    for name in _workflow_names():
        for _job, _step, run in _all_run_blocks(_workflow_yaml(name)):
            if "terraform apply" in run:
                appliers.add(name)
    assert appliers == {APPLY_WORKFLOW}, f"unexpected terraform apply sites: {sorted(appliers)}"
    # ...and that workflow is dispatch-only, so no ref, tag, path or timer
    # can start an apply.
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
    for name in ("infrastructure.yml", APPLY_WORKFLOW):
        for job_name, step_name, run in _all_run_blocks(_workflow_yaml(name)):
            body = [ln for ln in run.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            if len(body) < 2:
                continue  # single command: bash -e already fails the step
            if body[0].strip() != "set -euo pipefail":
                offenders.append(f"{name}:{job_name}:{step_name}")
    assert offenders == [], "multi-line run blocks without `set -euo pipefail`: " + ", ".join(
        offenders
    )


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
    # A machine-readable plan must exist for the validators to read.
    assert 'terraform show -json "tfplan-${PROFILE}" > "remote-plan-${PROFILE}.json"' in remote_plan

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
}


def test_promotion_plan_records_the_full_plan_provenance():
    doc = _workflow_yaml(APPLY_WORKFLOW)
    plan_script = _job_script(doc, "plan")
    for field, statement in PLAN_EVIDENCE.items():
        assert statement in plan_script, f"the reviewed plan no longer records {field}"
    # The lockfile digest is taken from the checked-out tree, before init can
    # touch it, so apply can compare it against the same commit's git content.
    assert plan_script.index("sha256sum .terraform.lock.hcl") < plan_script.index("terraform init")
    # Reports retained alongside the plan: the policy validator's canonical
    # inventory becomes the reviewed resource inventory.
    assert (
        'cp artifacts/profile-resource-inventory.json "${TF_DIR}/reviewed.resources.json"'
        in plan_script
    )
    assert 'tee "${TF_DIR}/reviewed.policy.txt"' in plan_script
    assert 'tee "${TF_DIR}/reviewed.cost.txt"' in plan_script
    assert '--inventory "${TF_DIR}/reviewed.resources.json"' in plan_script
    upload = next(
        s for s in _steps(doc, "plan") if str(s.get("uses", "")).startswith("actions/upload-artifact")
    )
    assert upload["with"]["path"].endswith("reviewed.*")
    assert upload["with"]["if-no-files-found"] == "error"


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
