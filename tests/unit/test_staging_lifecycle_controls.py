"""Staging must wake only through a reviewed plan, and must never stay awake.

Structural controls over `.github/workflows/staging-lifecycle.yml` and
`.github/workflows/staging-ttl-guard.yml`, in the style of
`test_release_workflow_controls.py`: raw workflow text where a substring is
unambiguous, parsed YAML wherever a substring assertion would be too weak to
mean anything (job graphs, `if:` conditions, step ordering, numeric bounds).
"""

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

LIFECYCLE = "staging-lifecycle.yml"
TTL_GUARD = "staging-ttl-guard.yml"
PROMOTE_WORKFLOW = "terraform-promote.yml"
PROMOTE_PATH = ".github/workflows/terraform-promote.yml"

# Every numeric bound the TTL guard declares. Each one must reach an
# enforcement decision; a bound that is only echoed is a control in name only.
TTL_BOUNDS = (
    "DEFAULT_MAX_AWAKE_HOURS",
    "MAX_AWAKE_HOURS_CAP",
    "MAX_EXTENSION_HOURS",
    "MAX_TOTAL_AWAKE_HOURS",
)

LIFECYCLE_ACTIONS = (
    "plan-wake",
    "apply-wake",
    "validate",
    "plan-sleep",
    "apply-sleep",
    "full-rehearsal",
)

# Every field terraform-promote.yml records with the reviewed plan. A caller that
# hands a plan to an apply must have looked at all of them.
REVIEWED_EVIDENCE = (
    "reviewed.tfplan",
    "reviewed.tfplan.json",
    "reviewed.tfplan.txt",
    "reviewed.tfplan.sha256",
    "reviewed.commit",
    "reviewed.profile",
    "reviewed.terraform-version",
    "reviewed.lock.sha256",
    "reviewed.state-key",
    "reviewed.created-utc",
    "reviewed.expires-utc",
    "reviewed.resources.json",
    "reviewed.policy.txt",
    "reviewed.cost.txt",
    "reviewed.staging-state",
)


def _workflow(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


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


def _on(doc: dict) -> dict:
    return doc.get("on", doc.get(True))


def _steps(doc: dict, job: str) -> list[dict]:
    return list(doc["jobs"][job].get("steps") or [])


def _job_script(doc: dict, job: str) -> str:
    return "\n".join(s["run"] for s in _steps(doc, job) if s.get("run"))


def _all_run_blocks(doc: dict):
    for job_name, job in (doc.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            if step.get("run"):
                yield job_name, step.get("name", "<unnamed>"), step["run"]


def _dispatch_steps(doc: dict) -> list[tuple[str, dict]]:
    """Every step that dispatches another workflow, with its owning job."""
    found = []
    for job_name, job in (doc.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            if step.get("run") and "gh workflow run" in step["run"]:
                found.append((job_name, step))
    return found


def _dispatch_invocations(run: str) -> list[str]:
    """Each `gh workflow run ...` invocation, backslash-continuations joined."""
    joined = re.sub(r"\\\n\s*", " ", run)
    return [
        line.strip()
        for line in joined.splitlines()
        if line.strip().startswith("gh workflow run")
    ]


def _referenced_text(doc: dict) -> str:
    """Everything in the workflow that can actually READ a value.

    `run:` bodies, `if:` conditions, step `env:` bindings and action inputs.
    Deliberately excludes the declaration blocks, so a knob that is declared and
    never consulted does not look consulted.
    """
    parts: list[str] = []
    for _job_name, job in (doc.get("jobs") or {}).items():
        if job.get("if"):
            parts.append(str(job["if"]))
        for name, value in (job.get("env") or {}).items():
            parts.append(f"{name}: {value}")
        for step in job.get("steps") or []:
            if step.get("if"):
                parts.append(str(step["if"]))
            if step.get("run"):
                parts.append(step["run"])
            for name, value in (step.get("env") or {}).items():
                parts.append(f"{name}: {value}")
            if step.get("with"):
                parts.append(yaml.safe_dump(step["with"]))
    return "\n".join(parts)


def _guard_step(step_id_or_name: str) -> dict:
    doc = _workflow_yaml(TTL_GUARD)
    return next(
        s
        for s in _steps(doc, "guard")
        if s.get("id") == step_id_or_name or s.get("name") == step_id_or_name
    )


def _embedded_python(run: str) -> str:
    """The `python - <<'PY' ... PY` body embedded in a run block."""
    assert "<<'PY'" in run, "the run block embeds no python heredoc"
    return run.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


def _run_lease_script(lease: str) -> dict:
    """Execute the guard's real lease-expiry script against one lease value."""
    env = dict(
        os.environ,
        LEASE=lease,
        DEFAULT_MAX_AWAKE_HOURS="4",
        MAX_AWAKE_HOURS_CAP="8",
        MAX_TOTAL_AWAKE_HOURS="12",
    )
    result = subprocess.run(
        [sys.executable, "-c", _embedded_python(_guard_step("state")["run"])],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _hours_from_now(hours: float) -> str:
    moment = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _lease(since_hours: float, until_hours: float, extensions: int = 0) -> str:
    return json.dumps({
        "awake_since": _hours_from_now(since_hours),
        "awake_until": _hours_from_now(until_hours),
        "extensions": extensions,
    })


def _enables_strict_bash(run: str) -> bool:
    """A real `set -euo pipefail`; a comment mentioning pipefail does not count."""
    for line in run.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return bool(re.match(r"set\s+-\S*e\S*u\S*", stripped)) and "pipefail" in stripped
    return False


# ---------------------------------------------------------------------------
# The action surface
# ---------------------------------------------------------------------------


def test_lifecycle_declares_every_required_action_and_nothing_else():
    doc = _workflow_yaml(LIFECYCLE)
    options = _on(doc)["workflow_dispatch"]["inputs"]["action"]["options"]
    assert set(options) == set(LIFECYCLE_ACTIONS), f"action surface drifted: {options}"


def test_every_action_is_actually_routed_to_work():
    """An option nobody branches on is a lie in the dispatch form."""
    doc = _workflow_yaml(LIFECYCLE)
    router = next(
        s for s in _steps(doc, "select-profile") if s.get("id") == "route"
    )
    run = router["run"]
    for action in LIFECYCLE_ACTIONS:
        assert re.search(rf"^\s*{re.escape(action)}\)", run, re.M), (
            f"lifecycle action {action} has no routing branch"
        )
    # An unrecognised action is rejected rather than silently doing nothing.
    assert "unknown lifecycle action" in run
    assert re.search(r"\*\)\s*echo .*unknown lifecycle action.*exit 1", run)

    # Each routing flag actually gates a job.
    flags = {
        "plan_wake": "wake-plan",
        "do_validate": "wake-validate",
        "apply_wake": "wake-apply",
        "rehearse": "rehearse",
        "plan_sleep": "sleep",
    }
    for flag, job in flags.items():
        condition = str(doc["jobs"][job]["if"])
        assert f"outputs.{flag}" in condition, f"{job} is not gated on {flag}"
    # apply_sleep gates the apply step inside the fail-safe sleep job.
    apply_step = next(s for s in _steps(doc, "sleep") if s.get("id") == "sleep-apply")
    assert "outputs.apply_sleep == 'true'" in str(apply_step["if"])


def test_lifecycle_and_guard_are_shaped_like_the_repo_expects():
    for name in (LIFECYCLE, TTL_GUARD):
        doc = _workflow_yaml(name)
        expected_permissions = (
            {"contents": "read", "actions": "write"}
            if name == LIFECYCLE
            else {"contents": "read"}
        )
        assert doc["permissions"] == expected_permissions, f"{name} top-level permissions"
        assert doc["concurrency"]["group"], f"{name} has no concurrency group"
        assert doc["concurrency"]["cancel-in-progress"] is False, (
            f"{name} may cancel a lifecycle run mid-mutation"
        )
        # id-token: write only where AWS OIDC is actually assumed.
        for job_name, job in doc["jobs"].items():
            assumes_aws = any(
                str(s.get("uses", "")).startswith("aws-actions/configure-aws-credentials")
                for s in job.get("steps") or []
            )
            grants_oidc = (job.get("permissions") or {}).get("id-token") == "write"
            assert grants_oidc == assumes_aws, (
                f"{name}:{job_name} id-token grant ({grants_oidc}) does not match "
                f"its AWS credential use ({assumes_aws})"
            )


def test_lifecycle_is_dispatch_only():
    assert _triggers(_workflow_yaml(LIFECYCLE)) == {"workflow_dispatch"}


# ---------------------------------------------------------------------------
# No path applies without a reviewed, checksum-verified plan
# ---------------------------------------------------------------------------


def test_neither_new_workflow_runs_terraform_itself():
    """The reviewed promotion workflow stays the only place terraform runs."""
    for name in (LIFECYCLE, TTL_GUARD):
        for job, step, run in _all_run_blocks(_workflow_yaml(name)):
            where = f"{name}:{job}:{step}"
            assert "terraform apply" not in run, f"{where} applies terraform directly"
            assert "terraform plan" not in run, f"{where} plans terraform directly"
            assert "terraform init" not in run, f"{where} initialises terraform directly"
            assert "-auto-approve" not in run, f"{where} auto-approves terraform"


def test_every_terraform_mutation_is_a_dispatch_of_the_reviewed_workflow():
    doc = _workflow_yaml(LIFECYCLE)
    dispatches = _dispatch_steps(doc)
    assert dispatches, "the lifecycle no longer reaches terraform-promote at all"
    for job, step in dispatches:
        invocations = _dispatch_invocations(step["run"])
        assert invocations, f"{job}:{step.get('name')} has no parseable dispatch"
        for invocation in invocations:
            assert '"$PROMOTE_WORKFLOW"' in invocation, (
                f"{job} dispatches something other than the reviewed workflow: {invocation}"
            )
            assert '-f profile="$STAGING_PROFILE"' in invocation, (
                f"{job} dispatches without pinning the staging profile"
            )
    assert doc["env"]["PROMOTE_WORKFLOW"] == PROMOTE_WORKFLOW
    assert doc["env"]["PROMOTE_WORKFLOW_PATH"] == PROMOTE_PATH


def test_every_promotion_dispatch_job_can_dispatch_workflows():
    """Job-level permissions must not override the dispatch capability.

    The lifecycle grants actions: write at the workflow level, but GitHub job
    permissions replace (rather than merge with) that declaration. Keeping
    this assertion next to the dispatch-structure checks prevents a future
    job-level actions: read from turning every wake/apply/sleep handoff into
    an opaque HTTP 403.
    """
    doc = _workflow_yaml(LIFECYCLE)
    for job_name, _step in _dispatch_steps(doc):
        permissions = doc["jobs"][job_name].get("permissions") or {}
        assert permissions.get("actions") == "write", (
            f"{job_name} dispatches terraform-promote but lacks actions: write"
        )


def test_every_promotion_dispatch_job_has_a_workspace_checkout():
    """The gh CLI requires the checked-out workspace even for API dispatches."""
    doc = _workflow_yaml(LIFECYCLE)
    for job_name, _step in _dispatch_steps(doc):
        uses = [str(step.get("uses", "")) for step in _steps(doc, job_name)]
        assert any(use.startswith("actions/checkout@") for use in uses), (
            f"{job_name} dispatches terraform-promote without a checkout; "
            "gh cannot run from the runner workspace"
        )


def test_no_apply_is_dispatched_without_a_verified_plan_run_and_checksum():
    doc = _workflow_yaml(LIFECYCLE)
    applies = []
    for job, step in _dispatch_steps(doc):
        for invocation in _dispatch_invocations(step["run"]):
            if "-f action=apply" in invocation:
                applies.append((job, step, invocation))
    assert applies, "nothing in the lifecycle applies a reviewed plan any more"
    for job, step, invocation in applies:
        assert '-f plan_run_id="$PLAN_RUN_ID"' in invocation, f"{job} applies without a plan run"
        assert '-f plan_checksum="$PLAN_CHECKSUM"' in invocation, f"{job} applies without a checksum"
        run = step["run"]
        # Refuse to dispatch on an empty identity.
        assert "no verified plan_run_id" in run or "no verified sleep plan_run_id" in run
        assert "no verified plan_checksum" in run or "no verified sleep plan_checksum" in run
        # The checksum handed to the apply is produced by a verification step in
        # this workflow, never read straight off a dispatch input.
        checksum_source = step["env"]["PLAN_CHECKSUM"]
        assert "steps." in checksum_source or "needs." in checksum_source, (
            f"{job} takes its plan checksum from {checksum_source}"
        )
        assert "inputs.plan_checksum" not in checksum_source, (
            f"{job} would apply a plan checksum straight from the dispatch form"
        )


def test_the_full_reviewed_evidence_set_is_verified_before_any_apply_dispatch():
    doc = _workflow_yaml(LIFECYCLE)
    for job in ("wake-validate", "sleep"):
        script = _job_script(doc, job)
        for artefact in REVIEWED_EVIDENCE:
            assert artefact in script, f"{job} never inspects {artefact}"
        assert "sha256sum --check --status reviewed.tfplan.sha256" in script, (
            f"{job} does not re-check the recorded plan digest"
        )
        assert 'test "$(cat reviewed.profile)" = "$PROFILE"' in script
        assert (
            'test "$(cat reviewed.state-key)" = "profiles/${PROFILE}/terraform.tfstate"'
            in script
        )
        assert "^[0-9a-f]{40}$" in script, f"{job} accepts a non-sha reviewed commit"

    # ...and the verification precedes the dispatch, in both wake and sleep.
    wake_steps = [s.get("id") or s.get("name", "") for s in _steps(doc, "wake-apply")]
    wake_validate_ids = [s.get("id") for s in _steps(doc, "wake-validate")]
    assert "reviewed" in wake_validate_ids
    assert doc["jobs"]["wake-apply"]["needs"] == [
        "select-profile",
        "wake-plan",
        "wake-validate",
        "preflight-rehearsal-inputs",
    ]
    assert "needs.wake-validate.result == 'success'" in str(doc["jobs"]["wake-apply"]["if"]), (
        "wake-apply can run without a successful validation"
    )
    assert wake_steps, "wake-apply lost its steps"

    sleep_ids = [s.get("id") for s in _steps(doc, "sleep")]
    assert sleep_ids.index("sleep-verify") < sleep_ids.index("sleep-apply"), (
        "the sleep plan is applied before it is verified"
    )
    apply_step = next(s for s in _steps(doc, "sleep") if s.get("id") == "sleep-apply")
    assert "steps.sleep-verify.outputs.plan_checksum != ''" in str(apply_step["if"]), (
        "the sleep apply is not gated on a verified checksum"
    )


def test_a_dispatched_apply_never_re_plans():
    doc = _workflow_yaml(LIFECYCLE)
    for job, step in _dispatch_steps(doc):
        for invocation in _dispatch_invocations(step["run"]):
            if "-f action=apply" not in invocation:
                continue
            assert "-f action=plan" not in invocation, f"{job} dispatches plan and apply at once"
            # An apply dispatch carries no plan-shaping inputs: it can only
            # consume the stored plan the plan_run_id names.
            for planning_input in ("staging_state=", "backend_image_digest=", "ml_image_digest="):
                assert planning_input not in invocation, (
                    f"{job} passes {planning_input} to an apply, which would imply a re-plan"
                )
    # The upstream guarantee this relies on still holds.
    promote = _workflow_yaml(PROMOTE_WORKFLOW)
    assert "terraform plan" not in _job_script(promote, "apply")
    assert "terraform apply -input=false reviewed.tfplan" in _job_script(promote, "apply")


def test_plan_expiry_and_window_are_enforced_before_apply():
    doc = _workflow_yaml(LIFECYCLE)
    for job in ("wake-validate", "sleep"):
        script = _job_script(doc, job)
        assert '"$((expires_epoch - created_epoch))" -gt 86400' in script, (
            f"{job} accepts a plan claiming more than 24 hours of validity"
        )
        assert "reviewed.expires-utc" in script
        assert re.search(r'-ge "\$expires_epoch"', script), (
            f"{job} does not reject an already-expired plan"
        )


def test_the_wake_plan_pins_the_approved_release_digest():
    doc = _workflow_yaml(LIFECYCLE)
    script = _job_script(doc, "wake-plan")
    assert "release_manifest.py" in script, "the wake plan trusts an unverified digest"
    assert "--checksum" in script and "--expected-sha" in script
    assert "belongs to ${run_path}, not the delivery workflow" in script, (
        "any run may be passed off as the approved release"
    )
    assert "concluded ${run_conclusion}, not success" in script
    assert "does not match the approved release manifest" in script, (
        "a caller-supplied backend digest may diverge from the manifest"
    )


# ---------------------------------------------------------------------------
# The pinned awake / asleep shape
# ---------------------------------------------------------------------------


def test_the_pinned_desired_counts_are_asserted_from_the_plan_itself():
    doc = _workflow_yaml(LIFECYCLE)
    for job, state in (("wake-validate", "awake"), ("sleep", "asleep")):
        step = next(
            s
            for s in _steps(doc, job)
            if s.get("run") and "planned ECS desired counts" in s["run"]
        )
        assert step["env"]["EXPECTED_STATE"] == state, f"{job} asserts the wrong state"
        run = step["run"]
        # The expectation is derived from canonical config, not hardcoded here,
        # and it is read out of the plan JSON rather than out of an evidence file.
        assert "config/runtime_deployment.yaml" in run
        assert "desired_count_multiplier" in run
        assert "planned_values" in run
        assert "aws_ecs_service" in run
        assert 'actual != expected' in run, f"{job} never compares plan against expectation"
    # asleep additionally means nothing may scale itself back up.
    sleep_script = _job_script(doc, "sleep")
    assert "aws_appautoscaling_target" in sleep_script
    assert "autoscaling floor" in sleep_script


def test_the_consolidated_worker_group_is_the_pinned_awake_shape():
    """`awake` is 1 API task + 1 lean-worker task, per the pinned interface."""
    runtime = yaml.safe_load((ROOT / "config" / "runtime_deployment.yaml").read_text())
    staging = (runtime.get("profiles") or {}).get("staging") or {}
    services = staging.get("services") or {}
    assert set(services) == {"api", "lean-worker"}, (
        f"the staging service set drifted from the pinned shape: {sorted(services)}"
    )
    assert services["api"]["desired_count"] == 1
    assert services["lean-worker"]["desired_count"] == 1
    assert len(services["lean-worker"]["roles"]) == 8, (
        "lean-worker no longer hosts all eight logical worker roles"
    )
    states = (staging.get("staging_state") or {}).get("states") or {}
    assert states["awake"]["desired_count_multiplier"] == 1
    assert states["asleep"]["desired_count_multiplier"] == 0


# ---------------------------------------------------------------------------
# The full rehearsal
# ---------------------------------------------------------------------------


REHEARSAL_PHASES = {
    "select the staging profile": (
        "select-profile",
        "Resolve the staging profile from canonical configuration",
    ),
    "credentialed wake plan": ("wake-plan", None),
    "validate plan policy": ("wake-validate", "Validate the reviewed plan against policy"),
    "validate the staging budget": ("wake-validate", "Validate the staging budget"),
    "apply the reviewed wake plan": ("wake-apply", None),
    "infrastructure readiness": ("wake-apply", "Wait for staging infrastructure readiness"),
}


def test_full_rehearsal_runs_every_declared_phase():
    doc = _workflow_yaml(LIFECYCLE)
    for label, (job, step_name) in REHEARSAL_PHASES.items():
        assert job in doc["jobs"], f"{label} has no job"
        if step_name:
            names = [s.get("name") for s in _steps(doc, job)]
            assert step_name in names, f"{label}: {job} lost the step {step_name!r}"

    rehearsal = " | ".join(s.get("name", "") for s in _steps(doc, "rehearse")).lower()
    for fragment in (
        "immutable application artifact",
        "migrations and verify the resulting revision",
        "readiness and frontend availability",
        "tenant isolation",
        "capability checks",
        "synthetic-seed exclusion and empty-state",
        "load test",
        "failure and retry",
        "rollback rehearsal",
        "collect logs, metrics, plans, test output and cost",
        "delete or expire the rehearsal tenant",
    ):
        assert fragment in rehearsal, f"the rehearsal lost its {fragment!r} phase"

    script = _job_script(doc, "rehearse")
    # The capability sweep must cover each named surface.
    for surface in ("auth", "consent", "ingest", "queue", "graph", "analytics", "ml"):
        assert surface in script.lower(), f"the rehearsal never touches {surface}"
    assert "RUN_MIGRATIONS" in script, "migrations are not run as a one-off task"
    assert "/v1/ready" in script, "the migration revision is never verified"


def test_first_staging_revision_records_rollback_as_not_applicable():
    script = _job_script(_workflow_yaml(LIFECYCLE), "rehearse")
    assert "status=not_applicable" in script
    assert "first approved staging revision" in script
    assert "no earlier task revision exists to roll back to" not in script


def test_the_rehearsal_verifies_the_running_image_is_the_approved_digest():
    script = _job_script(_workflow_yaml(LIFECYCLE), "rehearse")
    assert "not the approved ${image_uri}" in script, (
        "the rehearsal does not prove staging runs the approved image"
    )
    assert "the applied wake plan does not pin the approved release digest" in script


def test_the_rehearsal_tenant_is_always_removed():
    doc = _workflow_yaml(LIFECYCLE)
    step = next(
        s for s in _steps(doc, "rehearse") if s.get("name") == "Delete or expire the rehearsal tenant"
    )
    assert str(step["if"]).strip() == "always()", (
        "the rehearsal tenant survives a failed rehearsal"
    )
    run = step["run"]
    assert "-X DELETE" in run
    assert "/deactivate" in run, "there is no expiry fallback when delete is refused"
    assert "was neither deleted nor expired" in run


# ---------------------------------------------------------------------------
# Fail-safe sleep: runs always, and never hides the original failure
# ---------------------------------------------------------------------------


def test_sleep_runs_under_always():
    doc = _workflow_yaml(LIFECYCLE)
    condition = str(doc["jobs"]["sleep"]["if"])
    assert condition.startswith("always()"), f"the sleep job is conditional: {condition}"
    # It waits on every phase that could have left staging awake.
    assert set(doc["jobs"]["sleep"]["needs"]) == {
        "select-profile",
        "wake-plan",
        "wake-validate",
        "wake-apply",
        "rehearse",
    }
    # And the steps that stop cost run even when an earlier sleep step failed.
    for step_id in ("last-resort", "residual", "report"):
        step = next(s for s in _steps(doc, "sleep") if s.get("id") == step_id)
        assert str(step["if"]).startswith("always()"), (
            f"sleep step {step_id} is skipped once something fails"
        )


def test_sleep_never_suppresses_the_original_failure():
    doc = _workflow_yaml(LIFECYCLE)
    jobs = doc["jobs"]

    # Nothing in the lifecycle swallows its own exit status.
    for job_name, job in jobs.items():
        assert job.get("continue-on-error") in (None, False), (
            f"{job_name} is continue-on-error, so its failure cannot end the run red"
        )
        for step in job.get("steps") or []:
            assert step.get("continue-on-error") in (None, False), (
                f"{job_name}:{step.get('name')} is continue-on-error"
            )

    # A terminal gate re-raises whatever failed, including the cleanup itself.
    outcome = jobs["outcome"]
    assert str(outcome["if"]).strip() == "always()"
    assert set(outcome["needs"]) == set(jobs) - {"outcome"}, (
        "the outcome gate does not observe every phase"
    )
    script = _job_script(doc, "outcome")
    for result in (
        "SELECT_RESULT",
        "WAKE_PLAN_RESULT",
        "WAKE_VALIDATE_RESULT",
        "PREFLIGHT_RESULT",
        "WAKE_APPLY_RESULT",
        "REHEARSE_RESULT",
        "SLEEP_RESULT",
    ):
        assert result in script, f"the outcome gate ignores {result}"
    assert "failure|cancelled|timed_out" in script, (
        "the outcome gate does not recognise a failed phase"
    )
    assert "exit 1" in script, "the outcome gate cannot fail"
    assert '"${#failed[@]}" -ne 0' in script

    # The sleep job's own report is what carries the required disclosures.
    report = next(s for s in _steps(doc, "sleep") if s.get("id") == "report")
    body = report["run"]
    for disclosure in (
        "validation result",
        "cleanup result",
        "residual running/pending tasks",
        "estimated residual cost",
        "manual intervention required",
    ):
        assert disclosure in body, f"the cleanup report omits the {disclosure}"
    assert "exit 1" in body, "the cleanup report cannot fail on a bad cleanup"


def test_sleep_verifies_zero_desired_counts_and_prices_the_residual():
    doc = _workflow_yaml(LIFECYCLE)
    residual = next(s for s in _steps(doc, "sleep") if s.get("id") == "residual")
    run = residual["run"]
    assert "desiredCount" in run
    assert "still non-zero after sleep" in run, "a non-zero desired count is not an error"
    assert "describe-scalable-targets" in run, "an autoscaling floor could revive staging"
    assert "still hold a non-zero floor" in run
    # The residual cost is priced from the canonical price book, not a guess.
    assert "config/aws_price_book.yaml" in run
    assert "vcpu_hour" in run and "gb_hour" in run
    assert "residual_cost_usd_per_hour" in run

    # The verification happens after the sleep apply, not before it.
    ids = [s.get("id") for s in _steps(doc, "sleep")]
    assert ids.index("sleep-apply") < ids.index("residual")

    # The last-resort cost stop only fires when the reviewed sleep did not land,
    # and it can only ever reduce compute.
    last_resort = next(s for s in _steps(doc, "sleep") if s.get("id") == "last-resort")
    assert "steps.sleep-apply.outputs.conclusion != 'success'" in str(last_resort["if"])
    assert "--desired-count 0" in last_resort["run"]
    assert re.search(r"--desired-count [1-9]", last_resort["run"]) is None, (
        "the last-resort cost stop can scale staging UP"
    )
    assert 'test "$STAGING_CLUSTER" = "AETHER-staging"' in last_resort["run"], (
        "the last-resort cost stop is not pinned to the staging cluster"
    )


def test_the_evidence_bundle_is_checksummed():
    script = _job_script(_workflow_yaml(LIFECYCLE), "sleep")
    assert "sha256sum" in script
    assert "evidence.sha256" in script
    upload = next(
        s
        for s in _steps(_workflow_yaml(LIFECYCLE), "sleep")
        if str(s.get("uses", "")).startswith("actions/upload-artifact")
    )
    assert str(upload["if"]).strip() == "always()", "evidence is lost on a failed rehearsal"


# ---------------------------------------------------------------------------
# The TTL guard
# ---------------------------------------------------------------------------


def test_ttl_guard_is_actually_scheduled():
    doc = _workflow_yaml(TTL_GUARD)
    triggers = _triggers(doc)
    assert "schedule" in triggers, "the TTL guard is not on a timer at all"
    schedule = _on(doc)["schedule"]
    assert schedule, "the schedule block is empty"
    crons = [entry["cron"] for entry in schedule]
    assert crons, "no cron expression"
    for cron in crons:
        minute, hour = cron.split()[0], cron.split()[1]
        # At least hourly: a guard that runs daily cannot enforce a 4-hour TTL.
        assert minute != "*", f"cron {cron} fires every minute"
        assert hour == "*" or hour.startswith("*/"), (
            f"cron {cron} is coarser than hourly, so a 4h TTL can overrun badly"
        )


def test_ttl_guard_default_is_conservative_and_bounded():
    doc = _workflow_yaml(TTL_GUARD)
    env = doc["env"]
    default = int(env["DEFAULT_MAX_AWAKE_HOURS"])
    cap = int(env["MAX_AWAKE_HOURS_CAP"])
    total = int(env["MAX_TOTAL_AWAKE_HOURS"])
    extension = int(env["MAX_EXTENSION_HOURS"])
    assert default == 4, f"the conservative 4-hour default became {default}"
    assert 0 < default <= cap <= 12, f"cap {cap} is not a bound on the default"
    assert 0 < extension <= cap, f"an extension of {extension}h can exceed the cap"
    assert cap <= total <= 24, f"total awake ceiling {total} is not bounded"
    inputs = _on(doc)["workflow_dispatch"]["inputs"]
    assert int(inputs["extend_hours"]["default"]) <= extension


def test_the_ttl_guard_advertises_no_bound_it_does_not_enforce():
    """A knob that never reaches the expiry decision is a control in name only.

    `max_awake_hours` was a dispatch input documented as "1-8, default 4"; it
    was validated, exported and echoed, and then never consulted by the expiry
    comparison, which was lease-vs-now. The advertised TTL did not bind. It is
    gone: the enforced TTL is the lease's own window, which staging-lifecycle.yml
    chooses at wake time.
    """
    doc = _workflow_yaml(TTL_GUARD)
    used = _referenced_text(doc)

    inputs = _on(doc)["workflow_dispatch"]["inputs"]
    assert "max_awake_hours" not in inputs, (
        "a TTL input is advertised again; it must reach the expiry decision"
    )
    for name in inputs:
        assert f"inputs.{name}" in used, (
            f"{TTL_GUARD} advertises the input {name!r} but nothing reads it"
        )
    # Any input that claims to bound awake time must be read by the very step
    # that decides expiry, not merely validated and printed.
    state = _guard_step("state")
    state_env = " ".join(str(v) for v in (state.get("env") or {}).values())
    for name in inputs:
        if "awake" in name:
            assert f"inputs.{name}" in state_env, (
                f"{name} claims to bound awake time but never reaches the expiry decision"
            )

    for bound in TTL_BOUNDS:
        assert bound in doc["env"], f"{bound} is no longer declared"
        assert re.search(rf"\$\{{?{bound}\b", used) or bound in used, (
            f"{bound} is declared but never enters a decision"
        )
    # Named per decision, so a bound cannot drift into the wrong one.
    for bound in ("DEFAULT_MAX_AWAKE_HOURS", "MAX_AWAKE_HOURS_CAP", "MAX_TOTAL_AWAKE_HOURS"):
        assert bound in state["run"], f"the expiry decision ignores {bound}"
    assert "MAX_TOTAL_AWAKE_HOURS" in _guard_step("Grant a time-bounded extension")["run"]
    assert "MAX_EXTENSION_HOURS" in _guard_step("config")["run"]


def test_ttl_guard_extension_hours_are_range_checked():
    run = _guard_step("config")["run"]
    assert "must be a whole number of hours" in run, "a non-numeric extension is accepted"
    assert 'is outside 1..${MAX_EXTENSION_HOURS}' in run
    # A scheduled run always enforces; the timer path cannot be made advisory.
    assert 'if [ "$EVENT_NAME" = schedule ]; then' in run
    assert re.search(r'"\$EVENT_NAME" = schedule \]; then\s*\n\s*mode=enforce', run), (
        "a scheduled guard run does not force enforce mode"
    )


def test_ttl_guard_treats_a_missing_or_unreadable_lease_as_expired():
    run = _guard_step("state")["run"]
    assert "ParameterNotFound" in run
    assert "state_known=false" in run
    assert "|| echo ''" not in run
    script = _embedded_python(run)
    assert '"expired": True' in script, "the guard does not default to expired"
    assert script.count('out["expired"] = False') == 2, (
        "the number of ways to clear the expiry flag changed; each one needs review"
    )
    assert "is not a parseable UTC lease" in script
    # Behaviour, not text: run the guard's own script.
    for label, lease in (
        ("no lease at all", ""),
        ("whitespace", "   "),
        ("not a timestamp", "not-a-lease"),
        ("truncated json", '{"awake_since":'),
        ("json without a deadline", '{"awake_since":"2026-01-01T00:00:00Z"}'),
        ("deadline in the past", _lease(-5, -1)),
        ("wake time in the future", _lease(3, 5)),
    ):
        assert _run_lease_script(lease)["expired"] is True, (
            f"a lease that is {label} was treated as live"
        )
    # ...and a good lease is not killed mid-rehearsal.
    assert _run_lease_script(_lease(-1, 3))["expired"] is False


def test_a_single_lease_write_cannot_buy_unbounded_awake_time():
    """Anchored to `awake_since`, so the ceiling is the total awake window."""
    assert _run_lease_script(_lease(0, 4))["expired"] is False
    # Wider than MAX_AWAKE_HOURS_CAP for a lease nobody has extended.
    assert _run_lease_script(_lease(0, 10))["expired"] is True
    # An extended lease may reach MAX_TOTAL_AWAKE_HOURS, and no further.
    assert _run_lease_script(_lease(0, 10, extensions=2))["expired"] is False
    assert _run_lease_script(_lease(0, 13, extensions=3))["expired"] is True
    # Awake for longer than the total ceiling, however the deadline was reached.
    assert _run_lease_script(_lease(-13, 1, extensions=9))["expired"] is True
    # A legacy lease carries no anchor, so the conservative default bounds it.
    assert _run_lease_script(_hours_from_now(2))["expired"] is False
    assert _run_lease_script(_hours_from_now(6))["expired"] is True


def test_ttl_extensions_are_bounded_from_the_original_wake_not_the_latest_extend():
    """N sequential extends must not accumulate unbounded awake time.

    An extension REPLACES the deadline. Bounding it by `now + total` can never
    trip, because a single extension is capped at MAX_EXTENSION_HOURS which is
    smaller than the total; only the ORIGINAL wake anchors a real ceiling.
    """
    extend = _guard_step("Grant a time-bounded extension")
    assert "steps.config.outputs.mode == 'extend'" in str(extend["if"])
    run = extend["run"]
    # The extension is an absolute UTC deadline: it expires with the clock, with
    # no flag to unset and nothing to remember to revoke.
    assert 'date -u -d "+${EXTEND_HOURS} hours" +%Y-%m-%dT%H:%M:%SZ' in run
    assert "put-parameter" in run and "$AWAKE_LEASE_PARAM" in run
    # THE FIX: the ceiling is measured from the lease's awake_since.
    assert 'ceiling="$(date -u -d "${LEASE_SINCE} +${MAX_TOTAL_AWAKE_HOURS} hours"' in run, (
        "the extension ceiling is not anchored to the original wake"
    )
    assert re.search(r'ceiling="\$\(date -u -d "\+\$\{MAX_TOTAL_AWAKE_HOURS\} hours"', run) is None, (
        "the extension ceiling is measured from now, which no extension can ever exceed"
    )
    assert extend["env"]["LEASE_SINCE"] == "${{ steps.state.outputs.lease_since }}"
    # It refuses to extend what it cannot anchor, so there is no way around it.
    assert "refusing to extend: there is no parseable awake lease" in run
    assert "records no awake_since to bound the total against" in run
    # The replacement lease PRESERVES awake_since and counts the extension.
    assert '"awake_since":"%s"' in run, "the extension resets the original wake time"
    assert '"$LEASE_SINCE" "$new_deadline" "$extensions"' in run
    assert 'extensions="$(( ${LEASE_EXTENSIONS:-0} + 1 ))"' in run
    assert "refusing to extend a lease while staging is already asleep" in run, (
        "an extension can be banked before a rehearsal starts"
    )
    assert "extend_reason is required" in run, "extensions need not be justified"


def test_the_wake_lease_records_the_original_wake_time():
    """The guard's total-awake ceiling is unenforceable without it."""
    doc = _workflow_yaml(LIFECYCLE)
    step = next(s for s in _steps(doc, "wake-apply") if s.get("name") == "Open the awake lease")
    run = step["run"]
    assert '"awake_since":"%s"' in run and '"awake_until":"%s"' in run
    assert '"extensions":0' in run
    assert "put-parameter" in run and "$AWAKE_LEASE_PARAM" in run
    # The lease the lifecycle writes is one the guard actually accepts.
    assert _run_lease_script(_lease(0, 4))["expired"] is False


def test_an_unexpired_lease_is_not_killed_mid_rehearsal():
    """The whole point of the extension: enforcement is gated on expiry."""
    doc = _workflow_yaml(TTL_GUARD)
    enforce = next(s for s in _steps(doc, "guard") if s.get("id") == "enforce")
    condition = str(enforce["if"])
    assert "steps.state.outputs.ttl_expired == 'true'" in condition, (
        "the guard would scale staging to zero regardless of its lease"
    )
    assert "steps.config.outputs.mode == 'enforce'" in condition
    assert "steps.state.outputs.awake_tasks != '0'" in condition


def test_ttl_guard_enforcement_only_reduces_and_is_logged():
    doc = _workflow_yaml(TTL_GUARD)
    enforce = next(s for s in _steps(doc, "guard") if s.get("id") == "enforce")
    run = enforce["run"]
    assert 'test "$STAGING_CLUSTER" = "AETHER-staging"' in run, (
        "TTL enforcement is not pinned to the staging cluster"
    )
    assert "--desired-count 0" in run
    assert re.search(r"--desired-count [1-9]", run) is None, "enforcement can scale UP"
    assert "--min-capacity 0" in run, "an autoscaling floor survives enforcement"
    assert re.search(r"--min-capacity [1-9]", run) is None
    # Every cleanup action is written to a durable log that ships as evidence.
    assert "artifacts/ttl-guard/actions.log" in run
    assert "scaled_to_zero=" in run
    upload = next(
        s for s in _steps(doc, "guard") if str(s.get("uses", "")).startswith("actions/upload-artifact")
    )
    assert "artifacts/ttl-guard" in upload["with"]["path"]
    assert str(upload["if"]).strip() == "always()"


def test_ttl_guard_raises_a_blocking_alert_rather_than_passing_quietly():
    doc = _workflow_yaml(TTL_GUARD)
    alert = next(
        s
        for s in _steps(doc, "guard")
        if s.get("name") == "Blocking alert on an unaccountable staging environment"
    )
    assert str(alert["if"]).strip() == "always()"
    run = alert["run"]
    assert run.count("exit 1") >= 2, "the alert cannot fail the run"
    assert "could not bring it to zero" in run
    assert "was force-scaled to zero" in run
    assert "action: apply-sleep" in run, (
        "the alert does not tell operators how to reconcile Terraform state"
    )


def test_the_scheduled_guard_can_never_reach_a_terraform_apply():
    """terraform-promote.yml is dispatch-only so no timer can apply; keep it so."""
    doc = _workflow_yaml(TTL_GUARD)
    assert "schedule" in _triggers(doc)
    for job, step, run in _all_run_blocks(doc):
        assert "gh workflow run" not in run, f"{job}:{step} dispatches a workflow from a timer"
        assert "-f action=apply" not in run, f"{job}:{step} reaches an apply from a timer"
        assert "workflows/terraform-promote.yml/dispatches" not in run
    assert _triggers(_workflow_yaml(PROMOTE_WORKFLOW)) == {"workflow_dispatch"}


# ---------------------------------------------------------------------------
# Shell hygiene
# ---------------------------------------------------------------------------


def test_every_multiline_run_block_enables_strict_bash():
    """GitHub's default shell is `bash -e {0}`: no -u, and no pipefail."""
    offenders = []
    for name in (LIFECYCLE, TTL_GUARD):
        for job, step, run in _all_run_blocks(_workflow_yaml(name)):
            body = [ln for ln in run.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            if len(body) < 2:
                continue  # a single command: bash -e already fails the step
            if not _enables_strict_bash(run):
                offenders.append(f"{name}:{job}:{step}")
    assert offenders == [], "multi-line run blocks without `set -euo pipefail`: " + ", ".join(
        offenders
    )


def test_strict_bash_detection_rejects_a_comment_that_merely_says_pipefail():
    """Guards the guard: a sibling's equivalent test passed on a comment."""
    assert _enables_strict_bash("set -euo pipefail\nterraform version")
    assert not _enables_strict_bash("# set -euo pipefail\nterraform version")
    assert not _enables_strict_bash("echo 'pipefail'\nterraform version")
    assert not _enables_strict_bash("set -e\nterraform version")
    assert not _enables_strict_bash("set -eu\nterraform version")


def test_inputs_reach_shell_through_env_blocks_not_inline_interpolation():
    for name in (LIFECYCLE, TTL_GUARD):
        for job, step, run in _all_run_blocks(_workflow_yaml(name)):
            assert "${{" not in run, (
                f"{name}:{job}:{step} interpolates an expression straight into shell"
            )


def test_no_secret_is_interpolated_into_a_run_block():
    for name in (LIFECYCLE, TTL_GUARD):
        text = _workflow(name)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("run:") or stripped.startswith("- run:"):
                assert "secrets." not in stripped, f"{name}: inline secret in {stripped}"


# ---------------------------------------------------------------------------
# Fail-closed live state: an AWS call nobody checked proves nothing
# ---------------------------------------------------------------------------


def test_no_aws_call_is_read_through_an_unchecked_process_substitution():
    """`mapfile -t x < <(aws ...)` discards the AWS exit status.

    `pipefail` does not reach into a process substitution, so a throttle, an API
    error or an expired credential yields an EMPTY array — which every reader
    here interprets as "no services", i.e. "staging is asleep". Every AWS call
    must be run on its own with its status checked, and only then split.
    """
    offenders = []
    pattern = re.compile(r"<\s*<\(\s*aws\b")
    for name in (LIFECYCLE, TTL_GUARD):
        for job, step, run in _all_run_blocks(_workflow_yaml(name)):
            for line in re.sub(r"\\\n\s*", " ", run).splitlines():
                if pattern.search(line):
                    offenders.append(f"{name}:{job}:{step}: {line.strip()[:70]}")
    assert offenders == [], (
        "AWS output read through a process substitution, discarding its exit "
        "status: " + "; ".join(offenders)
    )


def test_no_aws_call_that_decides_staging_state_discards_its_stderr():
    """`2>/dev/null` on a state-deciding call hides the reason it failed.

    The one legitimate use is best-effort EVIDENCE collection, which is written
    into `artifacts/` and explicitly tolerated with `|| true`. Nothing reads
    those files to decide anything, and the exemption is narrow enough that a
    silenced decision cannot borrow it.
    """
    offenders = []
    for name in (LIFECYCLE, TTL_GUARD):
        for job, step, run in _all_run_blocks(_workflow_yaml(name)):
            for line in re.sub(r"\\\n\s*", " ", run).splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or "2>/dev/null" not in stripped:
                    continue
                if not re.search(r"\baws (ecs|application-autoscaling) ", stripped):
                    continue
                best_effort = "|| true" in stripped and "> artifacts/" in stripped
                if not best_effort:
                    offenders.append(f"{name}:{job}:{step}: {stripped[:70]}")
    assert offenders == [], (
        "an ECS/autoscaling call that decides whether staging is asleep swallows "
        "its stderr: " + "; ".join(offenders)
    )


def test_the_cleanup_gate_treats_an_unreadable_staging_state_as_not_asleep():
    """"Provably at zero" must not pass on the strength of a failed API call."""
    step = next(
        s for s in _steps(_workflow_yaml(LIFECYCLE), "sleep") if s.get("id") == "already"
    )
    run = step["run"]
    assert "asleep=true" in run
    # Every failure path publishes `unknown`, and none of them publishes `true`.
    assert run.count("asleep=unknown") == 3, (
        "not every unreadable-state path reports the state as unknown"
    )
    for guard in (
        'if ! services_raw="$(aws ecs list-services',
        'if ! nonzero="$(aws ecs describe-services',
    ):
        assert guard in run, f"{guard} is not status-checked"
    assert "must not be treated as asleep" in run
    # `asleep=true` has exactly two legitimate sources — a cluster that exposes
    # no services at all, and a successful describe reporting zero — and both
    # come AFTER the status check that proves the reading happened.
    assert run.count("asleep=true") == 2
    first_guard = run.index('if ! services_raw="$(aws ecs list-services')
    assert all(
        position > first_guard
        for position in (run.index("asleep=true"), run.rindex("asleep=true"))
    ), "staging can be declared asleep before its state was successfully read"
    assert re.search(r"''\|\*\[!0-9\]\*\)", run), (
        "a non-numeric desired-count reading is accepted as a count"
    )
    # An unknown state must not skip the reviewed sleep plan or the cost stop.
    doc = _workflow_yaml(LIFECYCLE)
    plan_step = next(s for s in _steps(doc, "sleep") if s.get("id") == "sleep-plan")
    assert "steps.already.outputs.asleep != 'true'" in str(plan_step["if"])
    last_resort = next(s for s in _steps(doc, "sleep") if s.get("id") == "last-resort")
    assert "steps.already.outputs.asleep != 'true'" in str(last_resort["if"])
    assert str(last_resort["if"]).startswith("always()")


def test_the_residual_check_never_reports_zero_it_could_not_measure():
    step = next(
        s for s in _steps(_workflow_yaml(LIFECYCLE), "sleep") if s.get("id") == "residual"
    )
    run = step["run"]
    # Each of the three AWS reads has a failure branch, and each sets zero_ok=false.
    assert run.count("zero_ok=false") == 5, (
        "a residual measurement path no longer fails closed"
    )
    assert run.count("residual_tasks=unknown") >= 1
    for message in (
        "could not enumerate staging ECS services",
        "could not describe staging ECS services",
        "could not read staging autoscaling targets",
    ):
        assert message in run, f"{message!r} is not reported"
    assert "must not be reported as zero" in run
    # The old swallow: `... > file 2>/dev/null || echo '[]' > file` made an
    # unreadable autoscaling namespace look empty.
    assert "|| echo '[]' > artifacts/sleep/autoscaling.json" not in run


def test_the_cleanup_report_fails_on_an_unproven_zero():
    report = next(
        s for s in _steps(_workflow_yaml(LIFECYCLE), "sleep") if s.get("id") == "report"
    )
    run = report["run"]
    assert '[ "${ZERO_OK:-false}" != true ]' in run, (
        "an absent zero_ok is not treated as a failure"
    )
    assert '[ "${ALREADY_ASLEEP:-unknown}" = unknown ]' in run, (
        "an unknown pre-sleep state does not fail the cleanup"
    )
    assert "never proven to be at zero" in run
    assert report["env"]["ZERO_OK"] == "${{ steps.residual.outputs.zero_ok }}"
    assert report["env"]["ALREADY_ASLEEP"] == "${{ steps.already.outputs.asleep }}"
    # The disclosure reaches the summary a human reads.
    assert "staging proven at zero after sleep" in run
    assert 'exit 1' in run


def test_the_ttl_guard_never_reports_asleep_on_an_unreadable_environment():
    """The guard's header promises fail-closed; live ECS state is part of that."""
    state = _guard_step("state")["run"]
    assert 'if ! services_raw="$(aws ecs list-services' in state
    assert "state_known=false" in state
    assert state.count("state_known=false") == 3, (
        "an unreadable-state path no longer publishes state_known=false"
    )
    assert "will not be reported as asleep" in state
    assert "state_known=true" in state
    # The verification pass reports `unknown`, never a fabricated zero.
    verify = _guard_step("verify")["run"]
    assert "residual=unknown" in verify
    assert 'if ! services_raw="$(aws ecs list-services' in verify
    assert "residual staging compute is UNKNOWN" in verify

    alert = _guard_step("Blocking alert on an unaccountable staging environment")
    run = alert["run"]
    assert alert["env"]["STATE_KNOWN"] == "${{ steps.state.outputs.state_known }}"
    assert 'state_known="${STATE_KNOWN:-false}"' in run, (
        "an absent state reading defaults to readable"
    )
    assert 'if [ "$state_known" != true ]' in run and "manual=true" in run
    # A non-numeric task count is unknown, and unknown demands a human.
    assert run.count("''|*[!0-9]*)") == 2, (
        "an unknown awake or residual task count is not detected"
    )
    # The `staging is asleep` notice is reachable only from a known-good reading.
    asleep_branch = run.split("::notice::staging is asleep")[0]
    assert 'if [ "$awake_known" = true ] && [ "${AWAKE_TASKS}" -gt 0 ]' in asleep_branch, (
        "the guard can announce that staging is asleep without having read it"
    )
    assert run.count("exit 1") >= 2


def test_the_ttl_guard_enforcement_fails_closed_on_an_unreadable_environment():
    run = _guard_step("enforce")["run"]
    assert 'if ! services_raw="$(aws ecs list-services' in run
    assert "TTL enforcement did not run" in run
    assert 'if ! targets_raw="$(aws application-autoscaling describe-scalable-targets' in run
    assert "an autoscaling floor may revive staging" in run


# ---------------------------------------------------------------------------
# The autoscaling namespace is account-wide: match the cluster exactly
# ---------------------------------------------------------------------------


def test_every_autoscaling_query_matches_the_staging_cluster_exactly():
    """`contains(ResourceId, 'AETHER-staging')` reaches other clusters.

    `describe-scalable-targets --service-namespace ecs` is ACCOUNT-WIDE and its
    ResourceId is `service/<cluster>/<service>`. A substring match hands an
    hourly cron the authority to zero the autoscaling floor of a service in any
    cluster whose name merely contains this one.
    """
    offenders, checked = [], 0
    for name in (LIFECYCLE, TTL_GUARD):
        for job, step, run in _all_run_blocks(_workflow_yaml(name)):
            if "describe-scalable-targets" not in run:
                continue
            checked += 1
            where = f"{name}:{job}:{step}"
            if "contains(ResourceId" in run:
                offenders.append(f"{where} matches the cluster by substring")
            if "starts_with(ResourceId, 'service/${STAGING_CLUSTER}/')" not in run:
                offenders.append(f"{where} does not anchor the cluster segment")
    assert checked >= 2, "the autoscaling queries disappeared rather than being fixed"
    assert offenders == [], "; ".join(offenders)


# ---------------------------------------------------------------------------
# The recorded staging_state is load-bearing, in both directions
# ---------------------------------------------------------------------------


def test_the_recorded_staging_state_is_asserted_in_both_wake_and_sleep():
    """It was written by terraform-promote.yml and read by nobody.

    The AUTHORITATIVE control on the applied shape is still the desired-count
    assertion against the plan JSON — this is the cheap cross-check that the
    plan under review is the one that was requested.
    """
    doc = _workflow_yaml(LIFECYCLE)
    expectations = {
        "wake-plan": "awake",
        "wake-validate": "awake",
        "sleep": "asleep",
    }
    for job, state in expectations.items():
        step = next(
            s for s in _steps(doc, job)
            if s.get("run") and "reviewed.staging-state" in s["run"]
        )
        assert step["env"]["EXPECTED_STATE"] == state, f"{job} expects the wrong state"
        assert 'test "$(cat reviewed.staging-state)" = "$EXPECTED_STATE"' in step["run"], (
            f"{job} reads the recorded staging_state without comparing it"
        )
        assert "not ${EXPECTED_STATE}" in step["run"]
        required = step["run"].split("for artefact in", 1)[1].split("do", 1)[0]
        assert "reviewed.staging-state" in required, (
            f"{job} does not require the recorded staging_state to be present"
        )
    # The stronger control it backs up is still the one doing the real work.
    assert "planned ECS desired counts" in _job_script(doc, "wake-validate")
    assert "planned ECS desired counts" in _job_script(doc, "sleep")
