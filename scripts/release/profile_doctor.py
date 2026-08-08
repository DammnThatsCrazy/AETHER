#!/usr/bin/env python3
"""Per-profile deployment readiness doctor + deployment certificate (§27/§28).

Deterministic, credentialless readiness report for a deployment profile. It is
the ``aether profile doctor <profile>`` surface: given a profile name it states
an explicit readiness state from a seven-rung ladder, and it can emit a
machine-readable ``deployment-certificate`` with a five-value result vocabulary
(passed / failed / not_applicable / pending_external / not_run).

READINESS LADDER (the state, never a percentage)
------------------------------------------------
  invalid                 unknown profile, unloadable config, or an in-repo
                          integrity check FAILED — the profile is not even ready
                          to wait for credentials
  development_only        local-class profile: coherent and runnable locally,
                          never a deployment target
  integration_ready       demo/preview-class profile: shared nonprod backends,
                          TTL lifecycle and seed declared — integration-testable
  credential_waiting      cloud-class profile whose every in-repo check passes;
                          the remaining work is exactly the credentialed /
                          external evidence, none of which is reachable from
                          this repository
  cloud_rehearsal_required  cloud-class profile where AWS credentials ARE
                          detectable but the credentialed rehearsal evidence is
                          not yet validated
  production_candidate    cloud rehearsal fully validated; production
                          certification evidence still pending (a fully
                          rehearsed staging sits here — it rehearses for
                          production, it is not production)
  production_certified    cloud-class profile whose entire external evidence
                          contract is validated (production-lean ceiling)

Honesty rules enforced structurally:
  * A cloud profile is CREDENTIAL_WAITING only when every in-repo check passes.
    A failing gate below it is INVALID, never "almost ready".
  * External evidence rows are pending_external unless a credentialed artifact
    is present AND carries structurally valid provenance AND an attestation a
    registered verifier can check. No verifier is registered in this repo, so
    pre-AWS the rows are pending_external by construction and the state is
    CREDENTIAL_WAITING — exactly the claim the monoprompt's §46 requires.
  * Credential detection is conservative: AWS env vars OR a credentialed
    artifact already on disk. Neither is treated as proof; both only advance
    the state to CLOUD_REHEARSAL_REQUIRED.

Usage:
  python scripts/release/profile_doctor.py staging
  python scripts/release/profile_doctor.py --all
  python scripts/release/profile_doctor.py staging --json
  python scripts/release/profile_doctor.py --all --gate        # run spine gates
  python scripts/release/profile_doctor.py --all --gate --certificate \
      release-evidence/profile/<profile>-certificate.json
  python scripts/release/profile_doctor.py --all --strict      # exit 1 below CW

Exit codes:
  0  every profile reported is not invalid (default), or --strict with every
     cloud profile at least credential_waiting
  1  a reported profile is invalid (integrity broken), or --strict and a cloud
     profile is below credential_waiting
  2  argument/config load failure
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from enum import Enum
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard, repo_root  # noqa: E402

CANONICAL_YAML = "config/deployment_profiles.yaml"
RUNTIME_YAML = "config/runtime_deployment.yaml"
CONTRACTS_YAML = "config/terraform_resource_contracts.yaml"
READINESS_YAML = "config/deployment_readiness.yaml"
TF_DIR = "AWS Deployment/aether-aws/terraform"
VARIABLES_TF = f"{TF_DIR}/variables.tf"
BUNDLE_ROOT = "release-evidence"

# The env template each cloud profile with a template is checked against.
ENV_TEMPLATES = {
    "staging": ".env.staging.example",
    "production-lean": ".env.production.example",
}

KNOWN_CLASSES = {"local", "demo", "preview", "staging", "production", "enterprise"}
LOCAL_CLASSES = frozenset({"local"})
INTEGRATION_CLASSES = frozenset({"demo", "preview"})
CLOUD_CLASSES = frozenset({"staging", "production", "enterprise"})

BACKEND_DIMS = ("database", "cache", "event", "graph", "analytics", "object", "ml")

# Canonical backend dimension -> env selector var.
BACKEND_SELECTOR_VARS = {
    "database": "DATABASE_BACKEND",
    "cache": "CACHE_BACKEND",
    "event": "EVENT_BACKEND",
    "graph": "GRAPH_BACKEND",
    "analytics": "ANALYTICS_BACKEND",
    "object": "OBJECT_BACKEND",
}

# Env vars that witness a forbidden dependency being suggested as an ACTIVE
# default in a cloud profile's template (msk/elasticache/neptune/clickhouse).
FORBIDDEN_ENV_WITNESSES = (
    "KAFKA_BROKERS",
    "KAFKA_BOOTSTRAP_SERVERS",
    "REDIS_HOST",
    "REDIS_PORT",
    "NEPTUNE_ENDPOINT",
    "CLICKHOUSE_HOST",
    "CLICKHOUSE_PORT",
)

# Spine validators run in --gate mode. These are the static, credentialless
# profile/cost/delivery gates; their exit codes become shared evidence rows.
SPINE_GATES = (
    ("spine-profile-config", "scripts/release/check_profile_config.py"),
    ("spine-profile-parity", "scripts/release/check_profile_parity.py"),
    ("spine-cost-policy", "scripts/release/check_cost_policy.py"),
    ("spine-cost-policy-terraform", "scripts/release/check_cost_policy_terraform.py"),
    ("spine-delivery-topology", "scripts/release/check_delivery_topology.py"),
)

# Result vocabulary (§28): passed / failed / not_applicable / pending_external /
# not_run. pending_external is the honest answer for anything that needs a
# credentialed action this repository cannot perform.
PASSED = "passed"
FAILED = "failed"
NOT_APPLICABLE = "not_applicable"
PENDING_EXTERNAL = "pending_external"
NOT_RUN = "not_run"


class Readiness(str, Enum):
    INVALID = "invalid"
    DEVELOPMENT_ONLY = "development_only"
    INTEGRATION_READY = "integration_ready"
    CREDENTIAL_WAITING = "credential_waiting"
    CLOUD_REHEARSAL_REQUIRED = "cloud_rehearsal_required"
    PRODUCTION_CANDIDATE = "production_candidate"
    PRODUCTION_CERTIFIED = "production_certified"


READINESS_RANK = {
    Readiness.INVALID: 0,
    Readiness.DEVELOPMENT_ONLY: 1,
    Readiness.INTEGRATION_READY: 2,
    Readiness.CREDENTIAL_WAITING: 3,
    Readiness.CLOUD_REHEARSAL_REQUIRED: 4,
    Readiness.PRODUCTION_CANDIDATE: 5,
    Readiness.PRODUCTION_CERTIFIED: 6,
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _git_sha() -> str:
    import subprocess as _sp

    try:
        return _sp.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(repo_root()),
            stderr=_sp.DEVNULL,
        ).decode().strip()
    except Exception:  # pragma: no cover - git optional
        return "unknown"


def _env_values(path: Path) -> dict[str, str]:
    """Parse ACTIVE (non-commented) KEY=VALUE lines, dropping inline comments."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, _, val = s.partition("=")
        val = re.split(r"\s+#", val, 1)[0].strip()
        out[key.strip()] = val
    return out


def _variables_tf_profiles(text: str) -> list[str] | None:
    m = re.search(
        r'contains\(\s*\[\s*((?:"[^"]+"\s*,\s*)*"[^"]+")\s*\]\s*,\s*var\.deployment_profile\s*\)',
        text,
    )
    if not m:
        return None
    return re.findall(r'"([^"]+)"', m.group(1))


# ---------------------------------------------------------------------------
# Check rows
# ---------------------------------------------------------------------------

def _row(cid: str, title: str, evidence: str, result: str, detail: str = "") -> dict:
    return {
        "id": cid,
        "title": title,
        "evidence": evidence,
        "result": result,
        "detail": detail,
    }


def _pass(cid: str, title: str, evidence: str, detail: str = "") -> dict:
    return _row(cid, title, evidence, PASSED, detail)


def _fail(cid: str, title: str, evidence: str, detail: str) -> dict:
    return _row(cid, title, evidence, FAILED, detail)


def _na(cid: str, title: str, evidence: str, detail: str = "") -> dict:
    return _row(cid, title, evidence, NOT_APPLICABLE, detail)


def _pending(cid: str, title: str, evidence: str, detail: str) -> dict:
    return _row(cid, title, evidence, PENDING_EXTERNAL, detail)


# ---------------------------------------------------------------------------
# In-repo (static) checks per profile
# ---------------------------------------------------------------------------

def _profile_static_checks(
    root: Path,
    profile: str,
    data: dict,
    profile_cfg: dict,
    contracts: dict,
    runtime: dict,
) -> list[dict]:
    checks: list[dict] = []
    cls = str(profile_cfg.get("class", ""))
    backends = profile_cfg.get("backends") or {}

    # 1. Backend dimensions all declared -------------------------------------
    missing = [d for d in BACKEND_DIMS if d not in backends]
    if missing:
        checks.append(_fail(
            "backends-declared",
            "every backend dimension declared",
            CANONICAL_YAML,
            f"missing backend dims: {missing}",
        ))
    else:
        checks.append(_pass(
            "backends-declared",
            "every backend dimension declared",
            CANONICAL_YAML,
        ))

    # 2. Profile class is known ----------------------------------------------
    if cls in KNOWN_CLASSES:
        checks.append(_pass("profile-class", "profile class is known", CANONICAL_YAML))
    else:
        checks.append(_fail(
            "profile-class", "profile class is known", CANONICAL_YAML,
            f"class {cls!r} is not in {sorted(KNOWN_CLASSES)}",
        ))

    # 3. Env-template parity (staging / production-lean) ----------------------
    if profile in ENV_TEMPLATES:
        tpl = root / ENV_TEMPLATES[profile]
        if not tpl.is_file():
            checks.append(_fail(
                "env-template-parity", "env template selectors match canonical backends",
                ENV_TEMPLATES[profile], "env template is absent",
            ))
        else:
            vals = _env_values(tpl)
            problems: list[str] = []
            for dim, var in BACKEND_SELECTOR_VARS.items():
                expected = backends.get(dim)
                actual = vals.get(var)
                if actual != expected:
                    problems.append(f"{var}={actual!r} != canonical {dim}={expected!r}")
            # EVENT_BROKER drives actual dispatch and defaults to kafka when
            # unset; a cloud profile whose event backend is sns_sqs must pin it.
            if backends.get("event") == "sns_sqs" and vals.get("EVENT_BROKER") != "sns_sqs":
                problems.append("EVENT_BROKER must be pinned to sns_sqs (runtime defaults to kafka)")
            active = {line.partition("=")[0].strip()
                      for line in tpl.read_text(encoding="utf-8").splitlines()
                      if line.strip() and not line.strip().startswith("#") and "=" in line}
            for witness in FORBIDDEN_ENV_WITNESSES:
                if witness in active:
                    problems.append(
                        f"active {witness} suggests a dependency the canonical "
                        f"{profile} profile forbids"
                    )
            if problems:
                checks.append(_fail(
                    "env-template-parity",
                    "env template selectors match canonical backends",
                    ENV_TEMPLATES[profile],
                    "; ".join(problems),
                ))
            else:
                checks.append(_pass(
                    "env-template-parity",
                    "env template selectors match canonical backends",
                    ENV_TEMPLATES[profile],
                ))
    else:
        checks.append(_na(
            "env-template-parity", "env template selectors match canonical backends",
            " — ".join(ENV_TEMPLATES.values()), "no dedicated env template for this profile",
        ))

    # 4. Terraform selectability (cloud profiles) -----------------------------
    if cls in CLOUD_CLASSES:
        tfvar = root / TF_DIR / "profiles" / f"{profile}.tfvars"
        variables_tf = root / VARIABLES_TF
        problems = []
        if not tfvar.is_file():
            problems.append(f"{TF_DIR}/profiles/{profile}.tfvars is absent")
        if not variables_tf.is_file():
            problems.append(f"{VARIABLES_TF} is absent")
        else:
            selectable = _variables_tf_profiles(variables_tf.read_text(encoding="utf-8"))
            if selectable is None or profile not in selectable:
                problems.append(f"{profile} is not in the variables.tf deployment_profile validation")
        if problems:
            checks.append(_fail(
                "terraform-selectable", "profile is selectable in Terraform",
                f"{TF_DIR}/profiles/{profile}.tfvars", "; ".join(problems),
            ))
        else:
            checks.append(_pass(
                "terraform-selectable", "profile is selectable in Terraform",
                f"{TF_DIR}/profiles/{profile}.tfvars",
            ))
    else:
        checks.append(_na(
            "terraform-selectable", "profile is selectable in Terraform",
            f"{TF_DIR}/profiles/*.tfvars",
            "non-cloud profile has no Terraform selection path",
        ))

    # 5. Runtime topology (cloud profiles) ------------------------------------
    if cls in CLOUD_CLASSES:
        runtime_profiles = set((runtime or {}).get("profiles", {}))
        if profile in runtime_profiles:
            checks.append(_pass(
                "runtime-topology", "profile has a runtime topology",
                RUNTIME_YAML,
            ))
        else:
            checks.append(_fail(
                "runtime-topology", "profile has a runtime topology",
                RUNTIME_YAML, f"{profile} has no entry in {RUNTIME_YAML}",
            ))
    else:
        checks.append(_na(
            "runtime-topology", "profile has a runtime topology",
            RUNTIME_YAML, "non-cloud profile does not need a cloud runtime topology",
        ))

    # 6. Cost-policy shape (profiles that declare one) ------------------------
    cost_policy = profile_cfg.get("cost_policy")
    if cost_policy:
        contract_classes = set()
        for section in ("required_resources", "forbidden_resources"):
            contract_classes.update((contracts or {}).get(section, {}).keys())
        problems = []
        for section in ("required_resources", "forbidden_resources"):
            items = cost_policy.get(section)
            if not isinstance(items, list) or not items:
                problems.append(f"cost_policy.{section} is missing or empty")
                continue
            for item in items:
                if item not in contract_classes:
                    problems.append(
                        f"cost_policy.{section} names {item!r}, which is not a "
                        f"known resource class in {CONTRACTS_YAML}"
                    )
        if problems:
            checks.append(_fail(
                "cost-policy-shape", "cost policy references known resource classes",
                CANONICAL_YAML, "; ".join(problems),
            ))
        else:
            checks.append(_pass(
                "cost-policy-shape", "cost policy references known resource classes",
                CANONICAL_YAML,
            ))
    else:
        checks.append(_na(
            "cost-policy-shape", "cost policy references known resource classes",
            CANONICAL_YAML, "profile declares no cost_policy block",
        ))

    # 7. Lifecycle declaration (demo/preview) ---------------------------------
    if cls in INTEGRATION_CLASSES:
        if profile_cfg.get("ttl_cleanup_required") is True:
            checks.append(_pass(
                "lifecycle-declared", "TTL cleanup required", CANONICAL_YAML,
            ))
        else:
            checks.append(_fail(
                "lifecycle-declared", "TTL cleanup required", CANONICAL_YAML,
                f"{profile} is integration-class but ttl_cleanup_required is not true",
            ))
    else:
        checks.append(_na(
            "lifecycle-declared", "TTL cleanup required", CANONICAL_YAML,
            "TTL lifecycle applies only to demo/preview profiles",
        ))

    return checks


# ---------------------------------------------------------------------------
# External (credentialed) evidence checks per profile
# ---------------------------------------------------------------------------

_AWS_ACCOUNT = re.compile(r"^[0-9]{12}$")
_AWS_REGION = re.compile(r"^[a-z]{2}(-gov)?-[a-z]+-[0-9]$")
_HEX_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")


def _provenance_shape_ok(data: dict) -> list[str]:
    """Structural provenance problems, if any. Never proof by itself."""
    prov = data.get("provenance")
    if not isinstance(prov, dict):
        return ["no `provenance` block"]
    reasons: list[str] = []
    if prov.get("credentialed") is not True:
        reasons.append("provenance.credentialed is not true")
    if not _AWS_ACCOUNT.fullmatch(str(prov.get("aws_account_id", ""))):
        reasons.append("aws_account_id is not a 12-digit account id")
    if not _AWS_REGION.fullmatch(str(prov.get("region", ""))):
        reasons.append("region is not an AWS region")
    if not _HEX_COMMIT.fullmatch(str(prov.get("commit_sha", ""))):
        reasons.append("commit_sha is not 7-40 hex")
    try:
        ts = datetime.datetime.fromisoformat(str(prov.get("captured_at", "")).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            reasons.append("captured_at is not timezone-aware")
    except (TypeError, ValueError):
        reasons.append("captured_at is not an ISO-8601 timestamp")
    return reasons


def _profile_external_checks(
    root: Path, profile: str, profile_cfg: dict, readiness: dict,
) -> list[dict]:
    cls = str(profile_cfg.get("class", ""))
    if cls not in CLOUD_CLASSES:
        return [_na(
            "external-evidence", "credentialed external evidence contract",
            f"{BUNDLE_ROOT}/", "non-cloud profile has no external evidence contract",
        )]

    controls = [c for c in (readiness or {}).get("controls", [])
                if c.get("profile") == profile]
    entries: list[tuple[str, str, str]] = []  # (control_id, evidence_id, path)
    for control in controls:
        for entry in control.get("required_evidence") or []:
            if entry.get("external"):
                entries.append((str(control.get("id")), str(entry.get("id")), str(entry.get("path"))))

    if not entries:
        return [_na(
            "external-evidence", "credentialed external evidence contract",
            f"{BUNDLE_ROOT}/",
            f"no scorecard controls are defined for {profile} in {READINESS_YAML}; "
            "its certification evidence contract is absent (scale/enterprise have none yet)",
        )]

    checks: list[dict] = []
    for control_id, evidence_id, path in sorted(entries):
        target = root / path
        cid = f"external.{control_id}.{evidence_id}"
        if not target.is_file():
            checks.append(_pending(
                cid, f"credentialed artifact for {control_id}",
                path,
                "artifact absent — awaiting the credentialed rehearsal/run that produces it",
            ))
            continue
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            checks.append(_pending(
                cid, f"credentialed artifact for {control_id}", path,
                f"artifact unreadable ({exc}); re-run the credentialed step",
            ))
            continue
        shape = _provenance_shape_ok(data)
        if shape:
            checks.append(_pending(
                cid, f"credentialed artifact for {control_id}", path,
                "artifact present but " + "; ".join(shape) +
                " — not credentialed evidence",
            ))
        else:
            # Structurally valid provenance is still self-declared until an
            # attestation verifier is registered (ATTESTATION_VERIFIERS is
            # empty), which happens when a real account exists to vouch for it.
            checks.append(_pending(
                cid, f"credentialed artifact for {control_id}", path,
                "artifact present with structurally valid provenance, but no "
                "attestation verifier is registered, so it cannot earn an "
                "externally-verified result from this repository",
            ))
    return checks


# ---------------------------------------------------------------------------
# Credential / external-state detection
# ---------------------------------------------------------------------------

def _credentials_available(root: Path) -> bool:
    aws_vars = (
        "AWS_ACCESS_KEY_ID", "AWS_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_SHARED_CREDENTIALS_FILE",
    )
    if any(os.environ.get(v) for v in aws_vars):
        return True
    evidence_root = root / BUNDLE_ROOT
    if not evidence_root.is_dir():
        return False
    for path in evidence_root.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover - unreadable artifact is not evidence
            continue
        if isinstance(data, dict) and (data.get("provenance") or {}).get("credentialed") is True:
            return True
    return False


def _external_status(external_checks: list[dict]) -> dict:
    contract_rows = [c for c in external_checks if c["result"] != NOT_APPLICABLE]
    all_validated = bool(contract_rows) and all(c["result"] == PASSED for c in contract_rows)
    return {
        "contract_rows": len(contract_rows),
        "all_validated": all_validated,
    }


# ---------------------------------------------------------------------------
# State derivation
# ---------------------------------------------------------------------------

def _derive_state(
    profile: str,
    profile_cfg: dict | None,
    inrepo_ok: bool,
    credentials_available: bool,
    external_checks: list[dict],
) -> Readiness:
    if profile_cfg is None:
        return Readiness.INVALID
    if not inrepo_ok:
        return Readiness.INVALID
    cls = str(profile_cfg.get("class", ""))
    if cls in LOCAL_CLASSES:
        return Readiness.DEVELOPMENT_ONLY
    if cls in INTEGRATION_CLASSES:
        return Readiness.INTEGRATION_READY
    # Cloud profiles.
    if not credentials_available:
        return Readiness.CREDENTIAL_WAITING
    status = _external_status(external_checks)
    if not status["all_validated"]:
        return Readiness.CLOUD_REHEARSAL_REQUIRED
    if profile == "staging":
        # A fully rehearsed staging is a promotion candidate, not production.
        return Readiness.PRODUCTION_CANDIDATE
    return Readiness.PRODUCTION_CERTIFIED


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def _run_spine_gates(root: Path) -> list[dict]:
    rows: list[dict] = []
    for gid, rel in SPINE_GATES:
        script = root / rel
        if not script.is_file():
            rows.append(_fail(gid, f"spine gate {rel}", rel, "gate script is absent"))
            continue
        proc = subprocess.run(
            [sys.executable, str(script)], cwd=str(root),
            capture_output=True, text=True, timeout=180,
        )
        tail = (proc.stdout + "\n" + proc.stderr).strip().splitlines()[-1:] or [""]
        if proc.returncode == 0:
            rows.append(_pass(gid, f"spine gate {rel}", rel, f"exit 0"))
        else:
            rows.append(_fail(
                gid, f"spine gate {rel}", rel,
                f"exit {proc.returncode}: {tail[-1]}",
            ))
    return rows


def build_profile_report(
    root: Path, profile: str, *, data: dict, contracts: dict, runtime: dict,
    readiness: dict, spine_rows: list[dict] | None,
) -> dict:
    profiles = (data or {}).get("profiles") or {}
    profile_cfg = profiles.get(profile)
    if profile_cfg is None:
        checks = [_fail(
            "profile-canonical", "profile exists in the canonical matrix",
            CANONICAL_YAML, f"{profile!r} is not in {CANONICAL_YAML}",
        )]
        return {
            "schema_version": 1,
            "profile": profile,
            "profile_class": "unknown",
            "readiness_state": Readiness.INVALID.value,
            "readiness_rank": READINESS_RANK[Readiness.INVALID],
            "generated_at": _now(),
            "commit_sha": _git_sha(),
            "checks": checks,
            "external_evidence_checks": [],
            "spine_gates": spine_rows or [],
            "summary": _summarize(checks + (spine_rows or [])),
            "external_evidence": {"credentials_available": False, "contract_rows": 0, "all_validated": False},
            "conclusion": f"{profile.upper()}: INVALID — not a canonical profile",
            "deployable": False,
        }

    checks = _profile_static_checks(root, profile, data, profile_cfg, contracts, runtime)
    external_checks = _profile_external_checks(root, profile, profile_cfg, readiness)
    all_rows = checks + external_checks + (spine_rows or [])
    inrepo_ok = all(c["result"] in (PASSED, NOT_APPLICABLE) for c in checks) and not any(
        c["result"] == FAILED for c in (spine_rows or [])
    )
    credentials = _credentials_available(root)
    state = _derive_state(profile, profile_cfg, inrepo_ok, credentials, external_checks)
    external_status = _external_status(external_checks)

    conclusion = _conclusion(profile, state, checks, external_checks, credentials, external_status)
    return {
        "schema_version": 1,
        "profile": profile,
        "profile_class": str(profile_cfg.get("class")),
        "readiness_state": state.value,
        "readiness_rank": READINESS_RANK[state],
        "generated_at": _now(),
        "commit_sha": _git_sha(),
        "checks": checks,
        "external_evidence_checks": external_checks,
        "spine_gates": spine_rows or [],
        "summary": _summarize(all_rows),
        "external_evidence": {
            "credentials_available": credentials,
            "contract_rows": external_status["contract_rows"],
            "all_validated": external_status["all_validated"],
        },
        "conclusion": conclusion,
        "deployable": state in (Readiness.PRODUCTION_CANDIDATE, Readiness.PRODUCTION_CERTIFIED),
    }


def _summarize(rows: list[dict]) -> dict[str, int]:
    summary = {k: 0 for k in (PASSED, FAILED, NOT_APPLICABLE, PENDING_EXTERNAL, NOT_RUN)}
    for row in rows:
        summary[row["result"]] = summary.get(row["result"], 0) + 1
    return summary


def _conclusion(
    profile: str, state: Readiness, checks: list[dict], external_checks: list[dict],
    credentials: bool, external_status: dict,
) -> str:
    failed = [c["id"] for c in checks if c["result"] == FAILED]
    if state == Readiness.INVALID and failed:
        return (
            f"{profile.upper()}: INVALID — {len(failed)} in-repo check(s) failed "
            f"({', '.join(failed[:4])}); a profile below this is not ready to wait "
            "for credentials"
        )
    if state == Readiness.DEVELOPMENT_ONLY:
        return f"{profile.upper()}: DEVELOPMENT_ONLY — local development profile, not a deployment target"
    if state == Readiness.INTEGRATION_READY:
        return (
            f"{profile.upper()}: INTEGRATION_READY — shared nonprod backends + TTL "
            "lifecycle declared; integration-testable"
        )
    if state == Readiness.CREDENTIAL_WAITING:
        pending = external_status["contract_rows"]
        return (
            f"{profile.upper()}: CREDENTIAL_WAITING — every in-repo check passes; "
            f"{pending} external evidence item(s) are pending credentialed runs. "
            "No AWS credentials or rehearsal evidence is reachable from this "
            "repository, so the externally-verified work is exactly what is left."
        )
    if state == Readiness.CLOUD_REHEARSAL_REQUIRED:
        return (
            f"{profile.upper()}: CLOUD_REHEARSAL_REQUIRED — AWS credentials are "
            "detectable but the credentialed rehearsal evidence is not yet "
            "validated; run the wake→deploy→migrate→smoke→load→rollback→sleep "
            "cycle and commit the evidence bundle"
        )
    if state == Readiness.PRODUCTION_CANDIDATE:
        return (
            f"{profile.upper()}: PRODUCTION_CANDIDATE — the cloud rehearsal is "
            "fully validated; promotion/certification evidence is the remaining step"
        )
    return (
        f"{profile.upper()}: PRODUCTION_CERTIFIED — the full external evidence "
        "contract is validated"
    )


def render_report(report: dict) -> None:
    r = Reporter(f"PROFILE DOCTOR — {report['profile']}")
    for row in (report["checks"]
                + report.get("external_evidence_checks", [])
                + report["spine_gates"]):
        mark = {"passed": "✓", "failed": "✗", "not_applicable": "·", "pending_external": "…", "not_run": "-"}.get(row["result"], "?")
        line = f"{mark} {row['id']} — {row['title']}"
        if row["detail"]:
            line += f" ({row['detail']})"
        if row["result"] == FAILED:
            r.fail(line)
        elif row["result"] == PASSED:
            r.ok(line)
        else:
            r.warn(line)
    r.ok(f"readiness: {report['readiness_state'].upper()} (rank {report['readiness_rank']})")
    r.ok(f"conclusion: {report['conclusion']}")
    r.finish()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profile", nargs="?", default=None,
                    help="Profile to doctor (default: all)")
    ap.add_argument("--all", action="store_true", help="Doctor every canonical profile")
    ap.add_argument("--json", action="store_true", help="Emit reports as JSON")
    ap.add_argument("--gate", action="store_true",
                    help="Run the static spine gates as additional evidence")
    ap.add_argument("--certificate", metavar="PATH", default=None,
                    help="Write each report's deployment certificate to PATH "
                         "({profile} is substituted in --all mode)")
    ap.add_argument("--strict", action="store_true",
                    help="Exit 1 unless every cloud profile is at least CREDENTIAL_WAITING")
    args = ap.parse_args(argv)

    root = repo_root()
    data = load_yaml(CANONICAL_YAML)
    if not isinstance(data, dict) or "profiles" not in data:
        print(f"{CANONICAL_YAML} is not a valid profile matrix", file=sys.stderr)
        return 2
    contracts = load_yaml(CONTRACTS_YAML) or {}
    runtime = load_yaml(RUNTIME_YAML) or {}
    readiness = load_yaml(READINESS_YAML) or {}

    profiles = sorted((data.get("profiles") or {}).keys())
    if args.profile and args.profile not in profiles and args.profile != "--all":
        # Still doctor it so the report says INVALID rather than silently passing.
        selected = [args.profile]
    elif args.all:
        selected = profiles
    elif args.profile:
        selected = [args.profile]
    else:
        selected = profiles

    spine_rows = _run_spine_gates(root) if args.gate else None

    reports = [
        build_profile_report(
            root, name, data=data, contracts=contracts, runtime=runtime,
            readiness=readiness, spine_rows=spine_rows,
        )
        for name in selected
    ]

    if args.json:
        print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2, sort_keys=True))
    else:
        for report in reports:
            render_report(report)

    if args.certificate:
        for report in reports:
            path = Path(args.certificate).expanduser()
            if "{profile}" in args.certificate:
                path = Path(args.certificate.format(profile=report["profile"]))
            out = path if path.is_absolute() else root / path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"  → {out.relative_to(root)}")

    # An INVALID profile always fails: it is a name typo or an in-repo
    # integrity break, and neither is a state a caller asked for by name.
    invalid = [r for r in reports if r["readiness_state"] == Readiness.INVALID.value]
    if invalid:
        for r in invalid:
            print(f"{r['profile']}: INVALID — see report", file=sys.stderr)
        return 1
    if args.strict:
        cloud_below = [
            r for r in reports
            if r["profile_class"] in CLOUD_CLASSES
            and READINESS_RANK[Readiness(r["readiness_state"])] < READINESS_RANK[Readiness.CREDENTIAL_WAITING]
        ]
        if cloud_below:
            for r in cloud_below:
                print(
                    f"strict gate: {r['profile'].upper()} is "
                    f"{r['readiness_state'].upper()}, below CREDENTIAL_WAITING",
                    file=sys.stderr,
                )
            return 1
    return 0


if __name__ == "__main__":
    main_guard(run)
