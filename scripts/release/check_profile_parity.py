#!/usr/bin/env python3
"""Cross-source deployment-profile parity validator.

One authoritative profile matrix exists — ``config/deployment_profiles.yaml`` —
and every other surface that states a profile count or a profile name must agree
with it. This validator is the CI tripwire for the "docs say ten, config has
eight" class of drift: it fails when any declared surface drifts, in EITHER
direction (a ninth profile added to the YAML fails until every surface is
updated; a surface claiming a profile the YAML removed fails immediately).

Surfaces cross-checked:

  1. DOCS — every registered doc that states a profile count ("eight deployment
     profiles", "the eight-profile matrix") must state the canonical count
     computed from the matrix. A ninth profile changes the count word and every
     registered doc fails until reviewed and updated.
  2. CLOUD SUBSET — the cloud-class profiles (class in {staging, production,
     enterprise}) must be exactly EXPECTED_CLOUD.
  3. SELECTABLE SET — the Terraform-selectable set is exactly cloud-class ∪
     ephemeral-class (class in {demo, preview}). ``check_cost_policy_terraform.py
     ::VALID_PROFILES``, the ``profiles/*.tfvars`` filenames, and the
     ``deployment_profile`` variable validation in ``variables.tf`` must all
     equal that selectable set.
  4. CONTRACT POLICY — every value in ``config/terraform_resource_contracts.yaml``
     ``permitted_in`` / ``also_applies_to`` must be a canonical profile.
  5. RUNTIME TOPOLOGY — every profile in ``config/runtime_deployment.yaml`` must
     be canonical, and every SELECTABLE profile must have a runtime topology.
  6. ENV TEMPLATES — ``DEPLOYMENT_PROFILE`` in ``.env.staging.example`` and
     ``.env.production.example`` must be a canonical profile (membership).
     Backend-parity with the profile's declared backends is enforced by
     ``tests/unit/test_release_profile_enforcement.py``.

Static analysis only; no Terraform binary or AWS credentials required.

Usage: python scripts/release/check_profile_parity.py
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard, repo_root  # noqa: E402

CANONICAL_YAML = "config/deployment_profiles.yaml"
CLOUD_CLASSES = {"staging", "production", "enterprise"}

# Docs that declare a profile count, with the phrase that must carry the
# canonical count word. Each pattern is matched as a REGEX so prose markdown
# (e.g. **eight**) around the count word is tolerated; `{word}` is the
# canonical count word, regex-escaped. Registering a doc here is deliberate:
# prose that states a number is exactly what the monoprompt's parity rule
# targets.
DOCS_COUNT_PHRASES = {
    "docs/DEPLOYMENT-PROFILES.md": [
        r"{word} deployment profiles",
        r"four of the \*{{0,2}}{word}\*{{0,2}}",
    ],
    "docs/STAGING-WAKE-SLEEP.md": [r"{word}-profile matrix"],
    "docs/COST-OPTIMIZATION.md": [r"{word}-profile matrix"],
}

# English count words for the small integers the canonical set can plausibly be.
_NUM_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
    15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
}

# The four cloud-class profiles. Cross-checked, not assumed.
EXPECTED_CLOUD = ["staging", "production-lean", "production-scale", "enterprise-isolated"]

# Ephemeral-class profiles are Terraform-selectable too (class in this set).
# They provision no NAT egress and are cost-capped/TTL-cleanup-required, but
# they are NOT part of the four cloud profiles the docs count as "four of the
# eight".
EPHEMERAL_CLASSES = {"demo", "preview"}

# The full Terraform-selectable set: cloud ∪ ephemeral.
EXPECTED_SELECTABLE = EXPECTED_CLOUD + ["demo", "preview"]

CHECK_COST_POLICY_TERRAFORM = "scripts/release/check_cost_policy_terraform.py"
TF_DIR = "AWS Deployment/aether-aws/terraform"
PROFILES_TF = f"{TF_DIR}/profiles.tf"
VARIABLES_TF = f"{TF_DIR}/variables.tf"
CONTRACTS_YAML = "config/terraform_resource_contracts.yaml"
RUNTIME_YAML = "config/runtime_deployment.yaml"


def _number_word(n: int) -> str:
    try:
        return _NUM_WORDS[n]
    except KeyError:
        raise ValueError(f"no English count word registered for {n} profiles")


def _read(rel_path: str) -> str:
    path = repo_root() / rel_path
    if not path.exists():
        raise FileNotFoundError(rel_path)
    return path.read_text(encoding="utf-8")


def _variables_tf_profiles(text: str) -> list[str] | None:
    """Extract the ``contains([...], var.deployment_profile)`` profile list.

    Tolerates both the single-line ``contains([...], var.deployment_profile)``
    form and the canonical ``terraform fmt`` multi-line form with a trailing
    comma after the last argument.
    """
    m = re.search(
        r'contains\(\s*\[\s*((?:"[^"]+"\s*,\s*)*"[^"]+")\s*\]\s*,\s*var\.deployment_profile\s*,?\s*\)',
        text,
    )
    if not m:
        return None
    return re.findall(r'"([^"]+)"', m.group(1))


def _selectable(profiles: dict) -> list[str]:
    """The Terraform-selectable set = cloud-class ∪ ephemeral-class profiles."""
    return sorted(
        p for p, cfg in profiles.items()
        if (cfg or {}).get("class") in (CLOUD_CLASSES | EPHEMERAL_CLASSES)
    )


def check() -> int:
    r = Reporter("PROFILE PARITY — cross-source profile-set agreement")

    data = load_yaml(CANONICAL_YAML)
    profiles = (data or {}).get("profiles", {})
    canonical = set(profiles)
    count = len(canonical)
    word = _number_word(count)

    # 1. Docs count parity --------------------------------------------------
    for doc, phrases in DOCS_COUNT_PHRASES.items():
        try:
            text = _read(doc)
        except FileNotFoundError:
            r.fail(f"{doc}: missing; registered as a profile-count doc")
            continue
        for phrase in phrases:
            expected_re = phrase.format(word=re.escape(word))
            r.require(
                re.search(expected_re, text, re.IGNORECASE) is not None,
                f"{doc} states '{phrase.format(word=word)}'",
                f"{doc} does not state a '{word} deployment profiles' count "
                f"(matrix has {count} profiles)",
            )

    # 2. Cloud-class subset ---------------------------------------------------
    cloud = sorted(p for p, cfg in profiles.items() if (cfg or {}).get("class") in CLOUD_CLASSES)
    expected_cloud = sorted(EXPECTED_CLOUD)
    r.require(
        cloud == expected_cloud,
        f"cloud-class subset == EXPECTED_CLOUD ({expected_cloud})",
        f"cloud-class subset mismatch: got {cloud}, expected {expected_cloud}",
    )

    # 3. Terraform selectability = cloud ∪ ephemeral --------------------------
    selectable = _selectable(profiles)
    expected_selectable = sorted(EXPECTED_SELECTABLE)
    r.require(
        selectable == expected_selectable,
        f"selectable set == cloud ∪ ephemeral ({expected_selectable})",
        f"selectable set mismatch: got {selectable}, expected {expected_selectable}",
    )

    cpt_source = _read(CHECK_COST_POLICY_TERRAFORM)
    m = re.search(r"VALID_PROFILES\s*=\s*(\[[^\]]*\])", cpt_source)
    r.require(
        m is not None,
        "check_cost_policy_terraform.py declares VALID_PROFILES",
        "check_cost_policy_terraform.py has no VALID_PROFILES literal",
    )
    if m:
        cpt_profiles = re.findall(r'"([^"]+)"', m.group(1))
        r.require(
            sorted(cpt_profiles) == selectable,
            f"VALID_PROFILES == selectable set ({selectable})",
            f"VALID_PROFILES mismatch: {cpt_profiles} != {selectable}",
        )

    tfvar_dir = repo_root() / TF_DIR / "profiles"
    tfvar_files = sorted(p.stem for p in tfvar_dir.glob("*.tfvars")) if tfvar_dir.exists() else []
    r.require(
        tfvar_files == selectable,
        f"profiles/*.tfvars == selectable set ({selectable})",
        f"profiles/*.tfvars mismatch: {tfvar_files} != {selectable}",
    )

    try:
        variables_tf = _read(VARIABLES_TF)
    except FileNotFoundError:
        r.fail(f"{VARIABLES_TF}: missing")
        variables_tf = ""
    var_profiles = _variables_tf_profiles(variables_tf)
    r.require(
        var_profiles is not None and sorted(var_profiles) == selectable,
        f"variables.tf deployment_profile validation == selectable set ({selectable})",
        f"variables.tf validation mismatch: {var_profiles} != {selectable}",
    )

    # 4. Contract policy references -------------------------------------------
    try:
        contracts = load_yaml(CONTRACTS_YAML)
    except FileNotFoundError:
        r.fail(f"{CONTRACTS_YAML}: missing")
        contracts = {}
    ref_ok = True
    for section in ("required_resources", "forbidden_resources"):
        for key, rule in (contracts or {}).get(section, {}).items():
            for field in ("permitted_in", "also_applies_to"):
                for value in (rule or {}).get(field, []):
                    if value not in canonical:
                        r.fail(
                            f"{CONTRACTS_YAML} {section}.{key}.{field} names "
                            f"non-canonical profile {value!r}"
                        )
                        ref_ok = False
    if ref_ok:
        r.ok(f"{CONTRACTS_YAML} permitted_in/also_applies_to reference only canonical profiles")

    # 5. Runtime topology -------------------------------------------------------
    try:
        runtime = load_yaml(RUNTIME_YAML)
    except FileNotFoundError:
        r.fail(f"{RUNTIME_YAML}: missing")
        runtime = {}
    runtime_profiles = set((runtime or {}).get("profiles", {}))
    r.require(
        runtime_profiles <= canonical,
        f"runtime_deployment.yaml profiles ⊆ canonical ({len(canonical)})",
        f"runtime_deployment.yaml names non-canonical profiles: "
        f"{sorted(runtime_profiles - canonical)}",
    )
    missing_runtime = sorted(p for p in selectable if p not in runtime_profiles)
    r.require(
        not missing_runtime,
        "every selectable profile has a runtime topology",
        f"selectable profiles missing runtime topology: {missing_runtime}",
    )

    # 6. Env template membership --------------------------------------------------
    for envf in (".env.staging.example", ".env.production.example"):
        try:
            text = _read(envf)
        except FileNotFoundError:
            r.fail(f"{envf}: missing")
            continue
        m = re.search(r"^DEPLOYMENT_PROFILE=(.*)$", text, re.MULTILINE)
        r.require(
            m is not None and m.group(1).strip() in canonical,
            f"{envf} DEPLOYMENT_PROFILE is canonical",
            f"{envf} DEPLOYMENT_PROFILE is missing or not canonical",
        )

    return r.finish()


if __name__ == "__main__":
    main_guard(check)
