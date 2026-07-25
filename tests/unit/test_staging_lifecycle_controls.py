"""Staging must wake only through a reviewed plan, and must never stay awake.

Structural controls over `.github/workflows/staging-lifecycle.yml` and
`.github/workflows/staging-ttl-guard.yml`, in the style of
`test_release_workflow_controls.py`: raw workflow text where a substring is
unambiguous, parsed YAML wherever a substring assertion would be too weak to
mean anything (job graphs, `if:` conditions, step ordering, numeric bounds).
"""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

LIFECYCLE = "staging-lifecycle.yml"
TTL_GUARD = "staging-ttl-guard.yml"
PROMOTE_WORKFLOW = "terraform-promote.yml"
PROMOTE_PATH = ".github/workflows/terraform-promote.yml"

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
        assert doc["permissions"] == {"contents": "read"}, f"{name} top-level permissions"
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
    # The dispatch input agrees with the environment default.
    inputs = _on(doc)["workflow_dispatch"]["inputs"]
    assert inputs["max_awake_hours"]["default"] == str(default)
    assert int(inputs["extend_hours"]["default"]) <= extension


def test_ttl_guard_configurable_maximum_is_range_checked():
    doc = _workflow_yaml(TTL_GUARD)
    config = next(s for s in _steps(doc, "guard") if s.get("id") == "config")
    run = config["run"]
    assert 'is outside 1..${MAX_AWAKE_HOURS_CAP}' in run, (
        "max_awake_hours is not bounded by the hard cap"
    )
    assert "must be a whole number of hours" in run, "a non-numeric TTL is accepted"
    # A scheduled run always enforces; the timer path cannot be made advisory.
    assert 'if [ "$EVENT_NAME" = schedule ]; then' in run
    assert re.search(r'"\$EVENT_NAME" = schedule \]; then\s*\n\s*mode=enforce', run), (
        "a scheduled guard run does not force enforce mode"
    )


def test_ttl_guard_treats_a_missing_or_unreadable_lease_as_expired():
    doc = _workflow_yaml(TTL_GUARD)
    state = next(s for s in _steps(doc, "guard") if s.get("id") == "state")
    run = state["run"]
    assert "ttl_expired=true" in run, "the guard does not default to expired"
    # The only way to become non-expired is a parseable lease still in the future.
    assert re.search(
        r'if \[ "\$lease_valid" = true \] && \[ "\$now_epoch" -lt "\$lease_epoch" \]', run
    ), "the guard can consider an unparseable or past lease live"
    assert "not a parseable UTC timestamp" in run
    assert "ttl_expired=false" in run
    assert run.count("ttl_expired=false") == 1, (
        "there is more than one way to clear the expiry flag"
    )
    # A lease longer than the total ceiling is rejected, so no single write buys
    # unbounded awake time.
    assert 'exceeds the ${MAX_TOTAL_AWAKE_HOURS}h total ceiling' in run


def test_ttl_extensions_are_time_bounded_and_expire_by_themselves():
    doc = _workflow_yaml(TTL_GUARD)
    extend = next(
        s for s in _steps(doc, "guard") if s.get("name") == "Grant a time-bounded extension"
    )
    assert "steps.config.outputs.mode == 'extend'" in str(extend["if"])
    run = extend["run"]
    # The extension is an absolute UTC deadline: it expires with the clock, with
    # no flag to unset and nothing to remember to revoke.
    assert 'date -u -d "+${EXTEND_HOURS} hours" +%Y-%m-%dT%H:%M:%SZ' in run
    assert "put-parameter" in run and "$AWAKE_LEASE_PARAM" in run
    assert "would exceed the ${MAX_TOTAL_AWAKE_HOURS}h total awake ceiling" in run
    assert "refusing to extend a lease while staging is already asleep" in run, (
        "an extension can be banked before a rehearsal starts"
    )
    assert "extend_reason is required" in run, "extensions need not be justified"
    # Bounds are checked before the extension is written.
    config = next(s for s in _steps(doc, "guard") if s.get("id") == "config")
    assert 'is outside 1..${MAX_EXTENSION_HOURS}' in config["run"]


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
