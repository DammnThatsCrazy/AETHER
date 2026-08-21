"""Regression tests for the provider-credential KMS wiring (§7).

The profile_plan.tftest.hcl run blocks assert `length(module.kms_credentials)
== 1`, which proves the module is instantiated — but it does NOT prove that
CREDENTIAL_KMS_KEY_ID reaches either task definition, that the task role is
granted the crypto policy, or that the toggle exists. Those are exactly the
lines that drift without breaking a plan test (an env var dropped from the
container definition plans fine; an unattached IAM policy plans fine). These
tests read the Terraform SOURCE and assert the wiring, so the failure surfaces
at `make ci-check` rather than in an applied environment where the cipher
starts failing closed at boot.

The toggle is the root variable `enable_credential_kms` (default true), NOT a
profiles.tf local: the throwaway `terraform test` apply run passes false so its
teardown can destroy every resource (the CMK carries `prevent_destroy`), while
every real deployment keeps the default true. The gates below therefore assert
the variable-default wiring, and the plan runs still assert the module is
present for the six profiles that require it.

The mutation cases are the point: each check below must FAIL when its line is
removed, or it is a spell-check rather than a guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TF = ROOT / "AWS Deployment/aether-aws/terraform"
MAIN = TF / "main.tf"
PROFILES_TF = TF / "profiles.tf"
ROOT_VARS = TF / "variables.tf"
ECS_MAIN = TF / "modules/ecs/main.tf"
ECS_VARS = TF / "modules/ecs/variables.tf"
ECS_OUTPUTS = TF / "modules/ecs/outputs.tf"
CONTRACTS = yaml.safe_load(
    (ROOT / "config/terraform_resource_contracts.yaml").read_text()
)
PROFILES = yaml.safe_load(
    (ROOT / "config/deployment_profiles.yaml").read_text()
)

CLOUD_PROFILES = ("staging", "production-lean", "production-scale",
                  "enterprise-isolated")


def _read(rel: str) -> str:
    return (TF / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The wiring contract, stated as checks over source text so the mutation cases
# below can be applied and asserted to FAIL.
# ---------------------------------------------------------------------------

def _problems(main: str, profiles_tf: str, root_vars: str, ecs_main: str,
              ecs_vars: str, ecs_outputs: str) -> list[str]:
    p: list[str] = []

    # 1. The root instantiates the module, gated by the root toggle. The gate
    #    is `var.enable_credential_kms`, not a profiles.tf local: the tftest
    #    apply run passes false so its throwaway apply can tear down, while
    #    production keeps the default true.
    if not re.search(r'module\s+"kms_credentials"\s*\{', main):
        p.append("main.tf does not instantiate module \"kms_credentials\"")
    if "count  = var.enable_credential_kms ? 1 : 0" not in main:
        p.append("kms_credentials module is not count-gated by var.enable_credential_kms")
    if "credential_kms_key_id = try(module.kms_credentials[0].key_id, \"\")" not in main:
        p.append("module.ecs is not handed the credential KMS key id")

    # 2. The task role is granted the least-privilege crypto policy.
    m = re.search(r'resource\s+"aws_iam_role_policy"\s+"credential_kms"\s*\{', main)
    if not m:
        p.append("main.tf has no aws_iam_role_policy.credential_kms attachment")
    else:
        block = main[m.end():]
        if "role   = module.ecs.task_role_name" not in block:
            p.append("credential_kms policy is not attached to the ECS task role")
        if "policy = module.kms_credentials[0].iam_policy_json" not in block:
            p.append("credential_kms policy does not come from the module's iam_policy_json")

    # 3. The toggle is a root variable defaulting to true — every cloud profile
    #    gets the CMK unless an operator explicitly disables it, and only the
    #    throwaway tftest apply run does. (profiles.tf carries no
    #    enable_credential_kms local anymore; the gate lives in variables.tf.)
    m = re.search(
        r'variable\s+"enable_credential_kms"\s*\{(.*?)\n\}', root_vars, re.S,
    )
    if not m:
        p.append("variables.tf has no enable_credential_kms variable")
    elif "default     = true" not in m.group(1):
        p.append("enable_credential_kms does not default to true")

    # 4. The ECS module accepts the key id and injects CREDENTIAL_KMS_KEY_ID
    #    into BOTH task definitions (api + every runtime service).
    if "variable \"credential_kms_key_id\"" not in ecs_vars:
        p.append("modules/ecs has no credential_kms_key_id variable")
    if "CREDENTIAL_KMS_KEY_ID" not in ecs_main:
        p.append("CREDENTIAL_KMS_KEY_ID is never injected into a task definition")
    # The backend task and the runtime-service task are separate concat() blocks;
    # asserting the env var appears at least twice guards against a wiring that
    # reaches only the api task while workers run the cipher with no key.
    if ecs_main.count("CREDENTIAL_KMS_KEY_ID") < 2:
        p.append("CREDENTIAL_KMS_KEY_ID is injected into only one task definition")

    # 5. The ECS module exposes the task role NAME (aws_iam_role_policy.role
    #    takes the name, not the ARN).
    if "output \"task_role_name\"" not in ecs_outputs:
        p.append("modules/ecs has no task_role_name output")

    # 6. Policy + contract agree on the required resource.
    rule = (CONTRACTS.get("required_resources") or {}).get("credential_kms") or {}
    if rule.get("module_address") != "module.kms_credentials":
        p.append("contract credential_kms.module_address is not module.kms_credentials")
    if rule.get("cardinality") != "exactly:2":
        p.append("contract credential_kms.cardinality is not exactly:2")
    for prof in CLOUD_PROFILES:
        req = (PROFILES["profiles"][prof].get("cost_policy") or {}).get(
            "required_resources") or []
        if "credential_kms" not in req:
            p.append(f"{prof} cost_policy does not require credential_kms")

    return p


def test_credential_kms_wiring_is_present():
    problems = _problems(
        MAIN.read_text(), PROFILES_TF.read_text(), ROOT_VARS.read_text(),
        ECS_MAIN.read_text(), ECS_VARS.read_text(), ECS_OUTPUTS.read_text(),
    )
    assert not problems, "provider-credential KMS wiring regressed:\n  " + \
        "\n  ".join(problems)


def test_dropping_credential_kms_env_fails(monkeypatch):
    """Remove the env injection and the guard must fail — this is the line
    `terraform test` cannot see (a task env var plans fine either way)."""
    text = ECS_MAIN.read_text()
    mutated = text.replace('{ name = "CREDENTIAL_KMS_KEY_ID", value = var.credential_kms_key_id },', "")
    assert mutated != text, "mutation was a no-op"
    problems = _problems(
        MAIN.read_text(), PROFILES_TF.read_text(), ROOT_VARS.read_text(),
        mutated, ECS_VARS.read_text(), ECS_OUTPUTS.read_text(),
    )
    assert problems, "removing CREDENTIAL_KMS_KEY_ID was not detected"


def test_dropping_iam_role_policy_fails():
    """Remove the task-role attachment and the guard must fail — an unattached
    policy plans fine, but the cipher then fails closed at every boot."""
    main = MAIN.read_text()
    m = re.search(r'resource\s+"aws_iam_role_policy"\s+"credential_kms"\s*\{', main)
    assert m, "no aws_iam_role_policy.credential_kms block to mutate"
    # Cut the whole resource block through its closing brace.
    end = main.index("}", main.index("iam_policy_json", m.end())) + 1
    mutated = main[:m.start()] + main[end:]
    problems = _problems(
        mutated, PROFILES_TF.read_text(), ROOT_VARS.read_text(),
        ECS_MAIN.read_text(), ECS_VARS.read_text(), ECS_OUTPUTS.read_text(),
    )
    assert problems, "removing the aws_iam_role_policy attachment was not detected"


def test_removing_module_from_root_fails():
    """Count-gate flipped off (or the module deleted) must be caught here as
    well as by terraform test."""
    main = MAIN.read_text()
    mutated = main.replace("count  = var.enable_credential_kms ? 1 : 0\n", "")
    assert mutated != main, "mutation was a no-op"
    problems = _problems(
        mutated, PROFILES_TF.read_text(), ROOT_VARS.read_text(),
        ECS_MAIN.read_text(), ECS_VARS.read_text(), ECS_OUTPUTS.read_text(),
    )
    assert problems, "uncounting the kms_credentials module was not detected"
