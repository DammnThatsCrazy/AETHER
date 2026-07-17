"""Release workflows must validate pull requests without mutating them."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


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
