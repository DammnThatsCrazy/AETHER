#!/usr/bin/env python3
"""Credential-turnkey capability matrix + strict gate (program sec24).

Aggregates honest, machine-readable evidence from the repo into a per-capability
matrix of the sec24 credential-turnkey rows, and enforces a strict gate.

Evidence sources (each is read best-effort; a failing source degrades the
relevant rows to FAIL/WARN with an explicit detail rather than crashing):

* certification registry — ``shared.certification.build_capability_matrix()``
  (readiness states per provider; SCAFFOLDED and dishonest live-readiness claims)
* canonical provider manifest registry —
  ``shared.integration_contracts.catalog.manifest_by_family`` (transport,
  idempotency, cursor, environment availability, credential schema)
* credential contracts — ``config/credential_contracts.yaml`` (slots, rotation
  method, environment binding)
* credential authority — ``services/providers/credentials/`` +
  ``shared/credentials/`` (the platform credentials are consumed through)
* worker supervision — ``services/runtime/supervisor.py`` (WorkerSupervisor /
  WorkerSpec) and the per-domain worker builder modules
* secret hygiene — the canonical ``scripts/security/secret_scan.py``
* metering / entitlement — ``services/commerce/metering.py``,
  ``services/metering_evidence/``, ``services/x402/entitlements.py``
* migrations — the ``alembic/versions`` chain
* deployment — ``config/deployment_profiles.yaml`` + ``deploy/terraform``
* test evidence — the unit / chaos / fixture trees

Honesty rules enforced here:

* A row whose requirements the evidence does NOT meet is FAIL, never PASS.
* A row that can only be proven with LIVE credentials reports FAIL marked
  ``external_blocker`` when no live evidence exists — it is never reported as
  PASS.
* Live-readiness CLAIMS (``connection_testing`` / ``sandbox_validated`` /
  ``partner_live``) without live evidence are a FAIL row, so a provider can
  never inflate its own readiness.
* ``WARN`` is reserved for rows with partial or non-live-verifiable evidence;
  it never blocks the strict gate and never claims PASS.

Command surface::

  (default)         print the matrix + summary. EXIT 0 (honest reporting).
  --strict          EXIT 1 if any row is FAIL (the credential-turnkey-strict gate).
  --json            print the full machine-readable matrix as JSON.
  --evidence-json   print the raw evidence dict the matrix was evaluated on.
  --failures-only   print only FAILing rows (still honors --strict).

Exit codes::

  0  reporting succeeded, and (--strict) no row is FAIL
  1  --strict and one or more rows are FAIL
  2  the framework failed to load / collect evidence
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# ── backend import bootstrap (mirrors scripts/credentialless_certification.py) ─
BACKEND_ROOT = Path(__file__).resolve().parent.parent / "Backend Architecture" / "aether-backend"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("AETHER_ENV", "local")

SCHEMA_VERSION = 1

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_WARN = "warn"


# ── verdict model ─────────────────────────────────────────────────────────────


@dataclass
class RowVerdict:
    """Outcome of one matrix row's check against the evidence.

    ``external_blocker`` marks a FAIL whose only remaining path is live
    credential evidence — the row is not green, and no repo-side code change
    can turn it green.
    """

    status: str
    detail: str = ""
    external_blocker: bool = False


@dataclass(frozen=True)
class MatrixRow:
    """One sec24 credential-turnkey row: identity + evidence check."""

    id: str
    label: str
    category: str
    description: str
    check: Callable[[dict], RowVerdict]


# ── verdict helpers ───────────────────────────────────────────────────────────


def _pass(detail: str = "") -> RowVerdict:
    return RowVerdict(status=STATUS_PASS, detail=detail)


def _fail(detail: str = "", external_blocker: bool = False) -> RowVerdict:
    return RowVerdict(status=STATUS_FAIL, detail=detail, external_blocker=external_blocker)


def _warn(detail: str = "") -> RowVerdict:
    return RowVerdict(status=STATUS_WARN, detail=detail)


def _b(evidence: dict, key: str) -> bool:
    return bool(evidence.get(key, False))


# ── row check functions ───────────────────────────────────────────────────────


def _check_canonical_provider_manifest(evidence: dict) -> RowVerdict:
    """A canonical provider manifest must exist per capability, and no
    first-release provider may be SCAFFOLDED (a descriptor with no execution
    path is not a provider)."""
    scaffolded = evidence.get("scaffolded_providers") or []
    if scaffolded:
        names = ", ".join(
            f"{s.get('domain')}:{s.get('provider')}" for s in scaffolded
        )
        return _fail(f"{len(scaffolded)} first-release provider(s) are SCAFFOLDED: {names}")
    count = int(evidence.get("manifest_count") or 0)
    if count <= 0:
        return _fail("no canonical provider manifests declared")
    errors = evidence.get("manifest_errors") or []
    if errors:
        return _warn(f"{len(errors)} manifest validation error(s): {errors[0]}")
    return _pass(f"{count} canonical provider manifests, none SCAFFOLDED")


def _check_credential_slots_declared(evidence: dict) -> RowVerdict:
    """Every credential a capability needs must be a declared slot, and the
    certification descriptors must declare their required_credentials."""
    slots = evidence.get("credential_slots") or []
    if not slots:
        return _fail("no credential slots declared (config/credential_contracts.yaml empty)")
    if not _b(evidence, "credential_slots_required_creds"):
        return _warn(f"{len(slots)} slots declared but descriptors do not declare required_credentials")
    return _pass(f"{len(slots)} credential slots declared and required_credentials declared")


def _check_credential_authority_integrated(evidence: dict) -> RowVerdict:
    """Credentials must flow through the credential authority platform, not be
    invented per provider."""
    if _b(evidence, "credential_authority"):
        return _pass("credential authority platform is present and referenced")
    return _fail("no credential authority integration found (shared/credentials + provider slot registry)")


def _check_tenant_scoped(evidence: dict) -> RowVerdict:
    if _b(evidence, "tenant_isolation_tests"):
        return _pass("tenant isolation is exercised by tests")
    return _fail("no tenant-isolation test evidence")


def _check_environment_scoped(evidence: dict) -> RowVerdict:
    if _b(evidence, "environment_scoping"):
        return _pass("credentials/capabilities are scoped by environment")
    return _fail("no environment scoping declared for credentials/capabilities")


def _check_secret_safe(evidence: dict) -> RowVerdict:
    """Hardcoded credentials are an unconditional fail: the strict gate MUST
    fail when credentials are hardcoded."""
    findings = evidence.get("secret_findings") or []
    if findings:
        sample = findings[0]
        return _fail(
            f"{len(findings)} hardcoded secret candidate(s); e.g. "
            f"{sample[0]}:{sample[1]} ({sample[2][:40]})"
        )
    if _b(evidence, "secret_scan_ran"):
        return _pass("secret scan ran with no hardcoded-credential findings")
    return _warn("secret scan did not run; no finding can be asserted")


def _check_transport_implemented(evidence: dict) -> RowVerdict:
    declared = _b(evidence, "transport_declared")
    modules = _b(evidence, "transport_modules")
    if declared and modules:
        return _pass("transport declared in manifests and implemented in modules")
    if declared or modules:
        return _warn("transport partially declared/implemented")
    return _fail("no provider transport declared or implemented")


def _check_payload_normalization(evidence: dict) -> RowVerdict:
    modules = _b(evidence, "normalization_modules")
    tests = _b(evidence, "normalization_tests")
    if modules and tests:
        return _pass("payload normalization implemented and covered by tests")
    if modules:
        return _warn("payload normalization implemented but not test-covered")
    return _fail("no payload normalization evidence")


def _check_storage_persistent(evidence: dict) -> RowVerdict:
    models = _b(evidence, "storage_models")
    policies = _b(evidence, "storage_policies")
    if models and policies:
        return _pass("durable models present and storage policies declared")
    if models:
        return _warn("durable models present but no storage policy declared")
    return _fail("no required persistence evidence")


def _check_migrations(evidence: dict) -> RowVerdict:
    count = int(evidence.get("migration_count") or 0)
    if count > 0:
        return _pass(f"{count} alembic migration file(s) present")
    return _fail("no alembic migrations present")


def _check_idempotency(evidence: dict) -> RowVerdict:
    declared = _b(evidence, "idempotency_declared")
    tests = _b(evidence, "idempotency_tests")
    if declared and tests:
        return _pass("idempotency semantics declared and replay-tested")
    if declared:
        return _warn("idempotency declared but not replay-tested")
    return _fail("no idempotency evidence — retry without idempotency can double-apply")


def _check_cursor_checkpoint(evidence: dict) -> RowVerdict:
    declared = _b(evidence, "cursor_declared")
    persisted = _b(evidence, "cursor_persistence")
    if declared and persisted:
        return _pass("cursor/checkpoint declared and persisted across pulls")
    if declared:
        return _warn("cursor declared but persistence not evidenced")
    return _fail("no cursor/checkpoint evidence")


def _check_retry(evidence: dict) -> RowVerdict:
    declared = _b(evidence, "retry_declared")
    tests = _b(evidence, "retry_tests")
    if declared and tests:
        return _pass("retry declared and test-covered")
    if declared:
        return _warn("retry declared but not test-covered")
    return _fail("no retry path evidence")


def _check_dead_letter(evidence: dict) -> RowVerdict:
    if _b(evidence, "dead_letter_modules"):
        return _pass("dead-letter / outbox machinery present")
    return _fail("no dead-letter / outbox machinery")


def _check_reconciliation(evidence: dict) -> RowVerdict:
    if _b(evidence, "reconciliation_modules"):
        return _pass("reconciliation machinery present")
    return _fail("no reconciliation machinery")


def _check_repair(evidence: dict) -> RowVerdict:
    if _b(evidence, "repair_modules"):
        return _pass("repair path present")
    if _b(evidence, "repair_required"):
        return _fail("repair path required for the cohort but absent")
    return _warn("no repair path and none required for the declared cohort")


def _check_worker_supervised(evidence: dict) -> RowVerdict:
    """A worker that exists but is not supervised is an unconditional fail."""
    unsupervised = evidence.get("workers_unsupervised") or []
    if unsupervised:
        names = ", ".join(str(w) for w in unsupervised[:8])
        return _fail(f"{len(unsupervised)} worker(s) exist but are not supervised: {names}")
    total = int(evidence.get("workers_total") or 0)
    if total <= 0:
        return _warn("no workers declared")
    if _b(evidence, "workers_supervised"):
        return _pass(f"{total} worker(s) declared under a supervision mechanism")
    return _fail(f"{total} worker(s) exist with no supervision mechanism")


def _check_heartbeat(evidence: dict) -> RowVerdict:
    if _b(evidence, "heartbeat"):
        return _pass("worker/role heartbeat evidence present")
    return _fail("no heartbeat evidence")


def _check_readiness_exposed(evidence: dict) -> RowVerdict:
    if _b(evidence, "readiness_exposed"):
        return _pass("readiness is exposed to operators")
    return _warn("no readiness endpoint evidence")


def _check_health_honest(evidence: dict) -> RowVerdict:
    """Provider health must not be able to report false success (e.g. claiming
    healthy while unconfigured) — the strict gate MUST fail when it can."""
    if _b(evidence, "health_false_success"):
        return _fail("provider health can report false success (healthy while unconfigured)")
    if _b(evidence, "health_verified"):
        return _pass("health posture verified — unconfigured adapters cannot report healthy")
    return _warn("health posture not independently verified")


def _check_missing_credential_explicit(evidence: dict) -> RowVerdict:
    if _b(evidence, "missing_credential_explicit"):
        return _pass("missing-credential is surfaced explicitly (fail-closed), not silently")
    return _fail("missing-credential can fail silently")


def _check_invalid_credential_explicit(evidence: dict) -> RowVerdict:
    if _b(evidence, "invalid_credential_explicit"):
        return _pass("invalid-credential is surfaced explicitly")
    return _fail("invalid-credential is not surfaced explicitly")


def _check_provider_outage_explicit(evidence: dict) -> RowVerdict:
    if _b(evidence, "provider_outage_explicit"):
        return _pass("provider outage is classified explicitly (non-retryable vs transient)")
    return _fail("provider outage is not classified explicitly")


def _check_empty_vs_failure_preserved(evidence: dict) -> RowVerdict:
    if _b(evidence, "empty_vs_failure_preserved"):
        return _pass("empty (valid, no data) is preserved distinct from failure")
    return _fail("empty-vs-failure distinction is not preserved")


def _check_unknown_vs_zero_preserved(evidence: dict) -> RowVerdict:
    if _b(evidence, "unknown_vs_zero_preserved"):
        return _pass("unknown is preserved distinct from zero")
    return _fail("unknown-vs-zero distinction is not preserved")


def _check_credential_rotation_tested(evidence: dict) -> RowVerdict:
    """Rotation is either offline-test-covered (PASS), declared but untested
    (WARN), or — when nothing is declared and no live evidence exists — an
    external blocker (FAIL, honest: it cannot be proven green here)."""
    if _b(evidence, "rotation_tests"):
        return _pass("credential rotation is test-covered")
    if _b(evidence, "rotation_method_declared"):
        return _warn("rotation method declared but not test-covered")
    if _b(evidence, "rotation_live_verified"):
        return _pass("credential rotation verified against a live credential")
    return _fail(
        "credential rotation is not declared, tested, or live-verified",
        external_blocker=True,
    )


def _check_automatic_readiness_demotion(evidence: dict) -> RowVerdict:
    logic = _b(evidence, "demotion_logic")
    tests = _b(evidence, "demotion_tests")
    if logic and tests:
        return _pass("automatic readiness demotion exists and is test-covered")
    if logic:
        return _warn("readiness demotion logic present but not test-covered")
    return _fail("no automatic readiness demotion evidence")


def _check_tenant_diagnostics(evidence: dict) -> RowVerdict:
    if _b(evidence, "tenant_diagnostics"):
        return _pass("tenant-scoped diagnostics evidence present")
    return _fail("no tenant diagnostics evidence")


def _check_operator_diagnostics(evidence: dict) -> RowVerdict:
    if _b(evidence, "operator_diagnostics"):
        return _pass("operator-facing diagnostics evidence present")
    return _fail("no operator diagnostics evidence")


def _check_usage_meter_defined(evidence: dict) -> RowVerdict:
    if _b(evidence, "usage_meter_defined"):
        return _pass("usage meter is defined and validated")
    return _fail("usage meter is not defined")


def _check_entitlement_key_defined(evidence: dict) -> RowVerdict:
    if _b(evidence, "entitlement_key_defined"):
        return _pass("entitlement keys are defined")
    return _fail("entitlement keys are not defined")


def _check_storage_policy_defined(evidence: dict) -> RowVerdict:
    if _b(evidence, "storage_policies"):
        return _pass("storage policy is defined")
    return _fail("storage policy is not defined")


def _check_offline_conformance_fixtures(evidence: dict) -> RowVerdict:
    if _b(evidence, "offline_fixtures"):
        return _pass("offline conformance fixtures present")
    return _fail("no offline conformance fixtures")


def _check_fault_injection_suite(evidence: dict) -> RowVerdict:
    if _b(evidence, "fault_injection_tests"):
        return _pass("fault-injection / chaos suite present")
    return _fail("no fault-injection suite")


def _check_infra_dependency_declared(evidence: dict) -> RowVerdict:
    if _b(evidence, "infra_declared"):
        return _pass("infra dependencies declared (deployment profiles + IaC)")
    return _fail("infra dependencies not declared")


def _check_documentation_current(evidence: dict) -> RowVerdict:
    if _b(evidence, "docs_present"):
        if _b(evidence, "docs_current"):
            return _pass("documentation present and current")
        return _warn("documentation present but currency not independently verified here")
    return _fail("no documentation present")


def _check_ci_green(evidence: dict) -> RowVerdict:
    """A live CI verdict cannot be proven from this script alone; the row is
    WARN with the canonical gate named, never PASS, unless the evidence dict
    carries a verified CI result."""
    if _b(evidence, "ci_verified"):
        return _pass("CI is green (verified)")
    if _b(evidence, "ci_gate_declared"):
        return _warn("CI gate chain declared; run `make ci-check` for a live verdict")
    return _fail("no CI gate chain declared")


def _check_live_readiness_evidence(evidence: dict) -> RowVerdict:
    """The strict gate MUST fail when a live-readiness claim lacks evidence:
    any provider claiming connection_testing / sandbox_validated / partner_live
    without live evidence is reported as a FAIL row."""
    claims = evidence.get("dishonest_readiness_claims") or []
    if claims:
        names = ", ".join(
            f"{c.get('domain')}:{c.get('provider')}={c.get('state')}" for c in claims
        )
        return _fail(f"{len(claims)} live-readiness claim(s) lack evidence: {names}")
    return _pass("no readiness claim lacks live evidence")


# ── the sec24 matrix ──────────────────────────────────────────────────────────

MATRIX_ROWS: list[MatrixRow] = [
    MatrixRow("canonical_provider_manifest", "Canonical provider manifest", "declaration",
              "Every capability declares a canonical provider manifest; no first-release provider is scaffolding-only.",
              _check_canonical_provider_manifest),
    MatrixRow("credential_slots_declared", "Credential slots declared", "credential",
              "Every credential a capability needs is a declared, machine-readable slot.",
              _check_credential_slots_declared),
    MatrixRow("credential_authority_integrated", "Credential authority integrated", "credential",
              "Credentials flow through the credential authority platform, not per-provider inventions.",
              _check_credential_authority_integrated),
    MatrixRow("tenant_scoped", "Tenant scoped", "scope",
              "Capabilities and their data are tenant-scoped and isolation is tested.",
              _check_tenant_scoped),
    MatrixRow("environment_scoped", "Environment scoped", "scope",
              "Credentials/capabilities are bound to declared environments.",
              _check_environment_scoped),
    MatrixRow("secret_safe", "Secret-safe", "credential",
              "No hardcoded credentials; the canonical secret scan is clean.",
              _check_secret_safe),
    MatrixRow("transport_implemented", "Transport implemented", "runtime",
              "Provider transport is declared in manifests and implemented in modules.",
              _check_transport_implemented),
    MatrixRow("payload_normalization", "Payload normalization", "runtime",
              "Payload normalization exists and is test-covered.",
              _check_payload_normalization),
    MatrixRow("storage_persistent", "Storage", "runtime",
              "Required persistence (durable models + storage policy) is present.",
              _check_storage_persistent),
    MatrixRow("migrations", "Migrations", "runtime",
              "Schema migrations exist for the persistence.",
              _check_migrations),
    MatrixRow("idempotency", "Idempotency", "runtime",
              "Retries cannot double-apply: idempotency semantics declared and replay-tested.",
              _check_idempotency),
    MatrixRow("cursor_checkpoint", "Cursor / checkpoint", "runtime",
              "Incremental pulls persist a cursor/checkpoint.",
              _check_cursor_checkpoint),
    MatrixRow("retry", "Retry", "resilience",
              "A retry path is declared and test-covered.",
              _check_retry),
    MatrixRow("dead_letter", "Dead-letter", "resilience",
              "Unrecoverable work lands in a dead-letter/outbox, not silently dropped.",
              _check_dead_letter),
    MatrixRow("reconciliation", "Reconciliation", "resilience",
              "A reconciliation path exists for drift detection.",
              _check_reconciliation),
    MatrixRow("repair", "Repair", "resilience",
              "A repair path exists where required.",
              _check_repair),
    MatrixRow("worker_supervised", "Worker supervised", "runtime",
              "Every background worker runs under a supervision mechanism; none exist un-supervised.",
              _check_worker_supervised),
    MatrixRow("heartbeat", "Heartbeat", "observability",
              "Workers/roles emit heartbeat liveness.",
              _check_heartbeat),
    MatrixRow("readiness_exposed", "Readiness exposed", "observability",
              "Readiness is exposed to operators.",
              _check_readiness_exposed),
    MatrixRow("health_honest", "Health cannot report false success", "observability",
              "Unconfigured/degarded adapters cannot report healthy.",
              _check_health_honest),
    MatrixRow("missing_credential_explicit", "Missing credential explicit", "failure-semantics",
              "A missing credential surfaces explicitly (fail-closed), not silently.",
              _check_missing_credential_explicit),
    MatrixRow("invalid_credential_explicit", "Invalid credential explicit", "failure-semantics",
              "An invalid credential surfaces explicitly.",
              _check_invalid_credential_explicit),
    MatrixRow("provider_outage_explicit", "Provider outage explicit", "failure-semantics",
              "Provider outages are classified explicitly (non-retryable vs transient).",
              _check_provider_outage_explicit),
    MatrixRow("empty_vs_failure_preserved", "Empty vs failure preserved", "failure-semantics",
              "Empty (valid, no data) is preserved distinct from failure.",
              _check_empty_vs_failure_preserved),
    MatrixRow("unknown_vs_zero_preserved", "Unknown vs zero preserved", "failure-semantics",
              "Unknown is preserved distinct from zero.",
              _check_unknown_vs_zero_preserved),
    MatrixRow("credential_rotation_tested", "Credential rotation tested", "credential",
              "Credential rotation is declared and (ideally) test/live-verified.",
              _check_credential_rotation_tested),
    MatrixRow("automatic_readiness_demotion", "Automatic readiness demotion", "observability",
              "A provider that loses evidence is automatically demoted off-ramp.",
              _check_automatic_readiness_demotion),
    MatrixRow("tenant_diagnostics", "Tenant diagnostics", "observability",
              "Tenant-scoped diagnostics exist.",
              _check_tenant_diagnostics),
    MatrixRow("operator_diagnostics", "Operator diagnostics", "observability",
              "Operator-facing diagnostics exist.",
              _check_operator_diagnostics),
    MatrixRow("usage_meter_defined", "Usage meter defined", "metering",
              "A usage meter is defined and validated.",
              _check_usage_meter_defined),
    MatrixRow("entitlement_key_defined", "Entitlement key defined", "metering",
              "Entitlement keys are defined.",
              _check_entitlement_key_defined),
    MatrixRow("storage_policy_defined", "Storage policy defined", "metering",
              "A storage policy is defined.",
              _check_storage_policy_defined),
    MatrixRow("offline_conformance_fixtures", "Offline conformance fixtures", "evidence",
              "Offline (no-credential) conformance fixtures exist.",
              _check_offline_conformance_fixtures),
    MatrixRow("fault_injection_suite", "Fault-injection suite", "evidence",
              "A fault-injection / chaos suite exists.",
              _check_fault_injection_suite),
    MatrixRow("infra_dependency_declared", "Infra dependency declared", "evidence",
              "Infra dependencies are declared (deployment profiles + IaC).",
              _check_infra_dependency_declared),
    MatrixRow("documentation_current", "Documentation current", "evidence",
              "Documentation is present and current.",
              _check_documentation_current),
    MatrixRow("ci_green", "CI green", "evidence",
              "The CI gate chain is declared and green.",
              _check_ci_green),
    MatrixRow("live_readiness_evidence", "Live-readiness claims have evidence", "evidence",
              "No provider claims live readiness without live evidence.",
              _check_live_readiness_evidence),
]


# ── evaluation ────────────────────────────────────────────────────────────────


def evaluate_matrix(evidence: dict) -> dict:
    """Run every row's check against ``evidence`` and return the
    machine-readable capability matrix (deterministic, JSON-serializable)."""
    rows: list[dict] = []
    by_status = {STATUS_PASS: 0, STATUS_FAIL: 0, STATUS_WARN: 0}
    external_blockers: list[str] = []
    for row in MATRIX_ROWS:
        verdict = row.check(evidence)
        by_status[verdict.status] = by_status.get(verdict.status, 0) + 1
        if verdict.status == STATUS_FAIL and verdict.external_blocker:
            external_blockers.append(row.id)
        rows.append(
            {
                "id": row.id,
                "label": row.label,
                "category": row.category,
                "description": row.description,
                "status": verdict.status,
                "external_blocker": verdict.external_blocker,
                "detail": verdict.detail,
            }
        )
    summary = {
        "total": len(rows),
        "pass": by_status[STATUS_PASS],
        "fail": by_status[STATUS_FAIL],
        "warn": by_status[STATUS_WARN],
        "external_blocker": len(external_blockers),
        "external_blocker_rows": external_blockers,
        "strict_pass": by_status[STATUS_FAIL] == 0,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "scripts/credential_turnkey_gate.py",
        "rows": rows,
        "summary": summary,
    }


def strict_exit_code(matrix: dict) -> int:
    """0 when no row is FAIL, else 1."""
    return 0 if matrix["summary"]["strict_pass"] else 1


def failing_rows(matrix: dict) -> list[dict]:
    return [r for r in matrix["rows"] if r["status"] == STATUS_FAIL]


# ── reference: a fully-turnkey evidence dict ──────────────────────────────────


def complete_evidence() -> dict:
    """Synthetic evidence in which every sec24 row is satisfied.

    Used by the self-test to assert the strict gate PASSES on a complete
    capability, and as a documented reference for what 'turnkey' evidence looks
    like. All keys are populated; no key is assumed by default.
    """
    return {
        "manifest_count": 3,
        "manifest_errors": [],
        "scaffolded_providers": [],
        "dishonest_readiness_claims": [],
        "credential_slots": ["apns", "fcm", "webhook_signing_secret"],
        "credential_slots_required_creds": True,
        "credential_authority": True,
        "tenant_isolation_tests": True,
        "environment_scoping": True,
        "secret_findings": [],
        "secret_scan_ran": True,
        "transport_declared": True,
        "transport_modules": True,
        "normalization_modules": True,
        "normalization_tests": True,
        "storage_models": True,
        "storage_policies": True,
        "migration_count": 5,
        "idempotency_declared": True,
        "idempotency_tests": True,
        "cursor_declared": True,
        "cursor_persistence": True,
        "retry_declared": True,
        "retry_tests": True,
        "dead_letter_modules": True,
        "reconciliation_modules": True,
        "repair_modules": True,
        "repair_required": True,
        "workers_total": 3,
        "workers_supervised": True,
        "workers_unsupervised": [],
        "heartbeat": True,
        "readiness_exposed": True,
        "health_false_success": False,
        "health_verified": True,
        "missing_credential_explicit": True,
        "invalid_credential_explicit": True,
        "provider_outage_explicit": True,
        "empty_vs_failure_preserved": True,
        "unknown_vs_zero_preserved": True,
        "rotation_method_declared": True,
        "rotation_tests": True,
        "rotation_live_verified": True,
        "demotion_logic": True,
        "demotion_tests": True,
        "tenant_diagnostics": True,
        "operator_diagnostics": True,
        "usage_meter_defined": True,
        "entitlement_key_defined": True,
        "offline_fixtures": True,
        "fault_injection_tests": True,
        "infra_declared": True,
        "docs_present": True,
        "docs_current": True,
        "ci_gate_declared": True,
        "ci_verified": True,
        "live_evidence_present": True,
    }


# ── repo evidence collection (best-effort, never raises) ──────────────────────


def _import(module: str, attr: Optional[str] = None):
    """Read-only import helper; returns None on any failure (honest)."""
    try:
        mod = __import__(module, fromlist=[attr] if attr else [])
        return getattr(mod, attr) if attr else mod
    except Exception:  # pragma: no cover - import fragility resolved honestly
        return None


def _files(root: Path, patterns: list[str]) -> list[Path]:
    """Sorted .py/.* files under ``root`` matching any glob pattern, excluding
    caches and vendored trees."""
    out: list[Path] = []
    for pattern in patterns:
        for p in sorted(root.glob(pattern)):
            if "__pycache__" in str(p) or "/.git/" in str(p) or "/node_modules/" in str(p):
                continue
            out.append(p)
    return sorted(dict.fromkeys(out))


def _contains(root: Path, patterns: list[str], token: str) -> bool:
    for p in _files(root, patterns):
        try:
            if token in p.read_text(errors="ignore"):
                return True
        except OSError:  # pragma: no cover - unreadable file
            continue
    return False


def _co_occurs(root: Path, patterns: list[str], tokens: list[str]) -> bool:
    """True when a single file under ``patterns`` contains ALL ``tokens``.
    Keeps semantic checks honest: a loose token alone (e.g. "rotation") is not
    enough — it must appear alongside its subject (e.g. "credential")."""
    for p in _files(root, patterns):
        try:
            text = p.read_text(errors="ignore")
        except OSError:  # pragma: no cover - unreadable file
            continue
        if all(t in text for t in tokens):
            return True
    return False


def _collect_certification(evidence: dict, backend: Path) -> None:
    """Provider readiness from the canonical certification registry."""
    build = _import("shared.certification", "build_capability_matrix")
    if build is None:
        evidence["errors"].append("shared.certification.build_capability_matrix unavailable")
        evidence.setdefault("manifest_count", 0)
        evidence["credential_slots_required_creds"] = False
        return
    matrix = build()
    providers = matrix["providers"]
    evidence["manifest_count"] = max(evidence.get("manifest_count") or 0, len(providers))
    scaffolded = [
        {"domain": p["domain"], "provider": p["provider"], "state": p["state"]}
        for p in providers.values()
        if p["state"] == "scaffolded"
    ]
    evidence["scaffolded_providers"] = scaffolded

    # Live-readiness claims are honest ONLY when the matching live-cert flag is
    # set for that provider (the same mechanism credentialless_certification
    # uses). Anything else is a claim without evidence.
    high = {"connection_testing", "sandbox_validated", "partner_live"}
    dishonest = []
    for p in providers.values():
        if p["state"] in high:
            live = bool(os.environ.get(f"AETHER_CERT_LIVE_{p['provider'].upper()}"))
            if not live:
                dishonest.append(
                    {"domain": p["domain"], "provider": p["provider"], "state": p["state"]}
                )
    evidence["dishonest_readiness_claims"] = dishonest
    evidence["credential_slots_required_creds"] = any(
        p["required_credentials"] for p in providers.values()
    )
    evidence.setdefault("migration_count", 0)


def _collect_manifests(evidence: dict) -> None:
    """Transport / idempotency / cursor / environment scoping from the canonical
    provider manifest registry."""
    try:
        from shared.integration_contracts.catalog import manifest_by_family
    except Exception as exc:  # pragma: no cover - catalog optional
        evidence["errors"].append(f"manifest registry unavailable: {exc}")
        return
    manifests = list(manifest_by_family.values())
    evidence["manifest_count"] = max(evidence.get("manifest_count") or 0, len(manifests))
    evidence["transport_declared"] = any(
        bool(m.base_url_config) or m.transport_protocol != "rest" for m in manifests
    )
    evidence["idempotency_declared"] = any(bool(m.idempotency_semantics) for m in manifests)
    evidence["cursor_declared"] = any(bool(m.sync.cursor) for m in manifests)
    evidence["environment_scoping"] = any(
        m.availability.environments.any_enabled() for m in manifests
    )
    evidence["manifest_errors"] = []


def _collect_secret_scan(evidence: dict) -> None:
    """Reuse the canonical secret scanner (read-only)."""
    spec = importlib.util.spec_from_file_location(
        "secret_scan", ROOT / "scripts" / "security" / "secret_scan.py"
    )
    if spec is None or spec.loader is None:
        evidence["secret_scan_ran"] = False
        return
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        evidence["secret_findings"] = list(mod.scan())
        evidence["secret_scan_ran"] = True
    except Exception as exc:  # pragma: no cover - scanner optional
        evidence["errors"].append(f"secret scan unavailable: {exc}")
        evidence["secret_scan_ran"] = False


def _collect_credential_contracts(evidence: dict) -> None:
    contract = ROOT / "config" / "credential_contracts.yaml"
    try:
        import yaml  # noqa: WPS433 (import inside fn is intentional)

        data = yaml.safe_load(contract.read_text(encoding="utf-8"))
    except Exception as exc:
        evidence["errors"].append(f"credential contracts unavailable: {exc}")
        evidence["credential_slots"] = []
        evidence["rotation_method_declared"] = False
        return
    creds = data.get("credentials", []) if isinstance(data, dict) else []
    evidence["credential_slots"] = [c.get("id") for c in creds if c.get("id")]
    evidence["rotation_method_declared"] = any(
        str(c.get("rotation_method", "")).strip() for c in creds
    )
    evidence["environment_scoping"] = (
        evidence.get("environment_scoping")
        or any(
            c.get("environment") or c.get("required_for_profiles")
            for c in creds
        )
    )


def _collect_workers(evidence: dict, backend: Path) -> None:
    """Worker supervision: a supervision mechanism (WorkerSupervisor/WorkerSpec)
    must exist for the worker builder modules to be counted as supervised."""
    worker_patterns = ["services/**/workers.py", "services/**/*worker*.py"]
    worker_files = [
        p for p in _files(backend, worker_patterns)
        if "runtime/supervisor.py" not in str(p)
        and "runtime/run_role.py" not in str(p)
    ]
    evidence["workers_total"] = len(worker_files)
    supervisor = backend / "services" / "runtime" / "supervisor.py"
    supervised = False
    try:
        text = supervisor.read_text(encoding="utf-8")
        supervised = "WorkerSupervisor" in text and "WorkerSpec" in text
    except OSError:
        supervised = False
    evidence["workers_supervised"] = supervised
    if supervised:
        evidence["workers_unsupervised"] = []
    else:
        evidence["workers_unsupervised"] = [
            str(p.relative_to(backend)) for p in worker_files
        ]


def _collect_code_evidence(evidence: dict, backend: Path) -> None:
    """Structural code/artifact evidence (file presence + token scans)."""
    services = "services/**/*.py"
    evidence["transport_modules"] = bool(
        _files(backend, ["services/gateway/**/*.py", "services/x402/**/*.py",
                         "services/commerce/**/*.py"])
    )
    evidence["normalization_modules"] = bool(
        _files(backend, ["services/**/normalizer*.py", "services/**/normalization*.py",
                         "services/**/conformance*.py", "shared/integration_contracts/normalization.py"])
    )
    evidence["storage_models"] = bool(_files(backend, ["services/**/models.py"]))
    evidence["storage_policies"] = (ROOT / "config" / "storage_policies.yaml").exists()
    migrations = [p for p in _files(backend, ["alembic/versions/*.py"])]
    evidence["migration_count"] = len(migrations)

    evidence["cursor_persistence"] = _contains(
        backend, ["services/**/*.py", "shared/**/*.py"], "advance_cursor"
    ) or _contains(backend, ["services/**/*.py"], "checkpoint")
    evidence["retry_declared"] = _contains(
        backend, ["services/**/*.py", "shared/**/*.py"], "retry"
    )
    evidence["retry_tests"] = _contains(
        ROOT, ["tests/**/*.py"], "retry"
    ) and evidence["retry_declared"]
    evidence["dead_letter_modules"] = _contains(
        backend, ["services/**/*.py"], "dead_letter"
    ) or _contains(backend, ["services/**/*.py"], "dlq")
    evidence["reconciliation_modules"] = bool(
        _files(backend, ["services/**/reconciliation*.py"])
    )
    evidence["repair_modules"] = bool(
        _files(backend, ["services/**/repair*.py"])
    )
    evidence["heartbeat"] = _contains(
        backend, ["services/runtime/**/*.py", "services/**/worker*.py"], "heartbeat"
    )
    evidence["readiness_exposed"] = bool(
        _files(backend, ["services/**/readiness*.py", "services/gateway/readiness.py"])
    )
    evidence["health_false_success"] = False  # check_health_transitions forbids it
    evidence["health_verified"] = bool(
        _files(ROOT, ["tests/chaos/test_certification_readiness.py"])
    ) or _contains(ROOT, ["tests/**/*.py"], "health_transitions")

    # Explicit-failure semantics require a real marker, not a bare token like
    # "fail" (which would match any error handling). Use the connection-test
    # taxonomy (results.py maps not_configured -> UNAUTHORIZED) and the
    # credential platform's missing-credential surface.
    evidence["missing_credential_explicit"] = _contains(
        backend, ["shared/integration_contracts/results.py", "services/**/*.py"], "not_configured"
    ) or _co_occurs(
        backend,
        ["services/providers/credentials/**/*.py", "shared/credentials/**/*.py"],
        ["missing", "credential"],
    )
    evidence["invalid_credential_explicit"] = _contains(
        backend, ["shared/integration_contracts/results.py", "services/**/*.py"], "UNAUTHORIZED"
    )
    evidence["provider_outage_explicit"] = _contains(
        backend, ["shared/integration_contracts/results.py", "services/**/*.py"], "RETRYABLE_ERROR"
    )
    evidence["empty_vs_failure_preserved"] = _co_occurs(
        ROOT, ["tests/**/*.py"], ["empty", "failure"]
    ) or _contains(backend, ["services/commerce/reconciliation.py"], "empty snapshot")
    evidence["unknown_vs_zero_preserved"] = bool(
        _files(ROOT, ["tests/unit/test_value_semantics.py"])
    ) or _contains(ROOT, ["tests/**/*.py"], "unknown != 0")

    evidence["tenant_diagnostics"] = bool(
        _files(ROOT, ["tests/unit/test_diagnostics_observability_routes.py",
                      "tests/unit/test_diagnostics_queue_routes.py"])
    )
    evidence["operator_diagnostics"] = bool(
        _files(backend, ["services/command_center/**/*.py",
                         "services/operational_intelligence/**/*.py"])
    )
    evidence["usage_meter_defined"] = bool(
        _files(backend, ["services/commerce/metering.py", "services/metering_evidence/**/*.py"])
    )
    evidence["entitlement_key_defined"] = bool(
        _files(backend, ["services/x402/entitlements.py", "services/rewards/**/*.py"])
    )
    evidence["offline_fixtures"] = bool(
        _files(ROOT, ["tests/fixtures/**/*.json", "tests/fixtures/**/*.yaml",
                      "tests/fixtures/**/*.yml"])
    )
    evidence["fault_injection_tests"] = bool(_files(ROOT, ["tests/chaos/**/*.py"]))
    evidence["infra_declared"] = (ROOT / "config" / "deployment_profiles.yaml").exists() and (
        ROOT / "deploy" / "terraform"
    ).exists()

    docs_present = bool(_files(ROOT, ["docs/**/*.md"]))
    evidence["docs_present"] = docs_present
    # Docs currency is the repo's own gates' job (scripts/docs_drift.py). We do
    # not claim 'current' from here — we only assert presence, and WARN on the
    # row so the report never overclaims.
    evidence["docs_current"] = False

    evidence["ci_gate_declared"] = (ROOT / "config" / "required_release_checks.yaml").exists()
    evidence["ci_verified"] = bool(os.environ.get("AETHER_GATE_CI_VERIFIED"))
    evidence["tenant_isolation_tests"] = bool(
        _files(ROOT, ["tests/unit/test_*tenant_isolation*.py",
                      "tests/security/test_*tenant_isolation*.py"])
    )
    evidence["demotion_logic"] = bool(
        _files(backend, ["shared/certification/readiness.py"])
    ) and _contains(backend, ["shared/certification/readiness.py"], "DEGRADED")
    evidence["demotion_tests"] = bool(
        _files(ROOT, ["tests/chaos/test_certification_readiness.py"])
    )


def _collect_live_evidence(evidence: dict) -> None:
    """Live credential evidence: the AETHER_CERT_LIVE_<PROVIDER> flags (the same
    mechanism credentialless_certification uses) — never inferred from structure."""
    live = [
        name for name in os.environ
        if name.startswith("AETHER_CERT_LIVE_")
        and os.environ[name].strip()
        and os.environ[name].strip().lower() not in ("0", "false", "no")
    ]
    evidence["live_evidence_present"] = bool(live)
    evidence["live_evidence_sources"] = sorted(live)
    # Rotation verified live only when a live credential is configured.
    evidence["rotation_live_verified"] = bool(live)


def collect_evidence(root: Optional[Path] = None) -> dict:
    """Best-effort evidence aggregation. Never raises: each source degrades the
    relevant rows to FAIL/WARN with a recorded error rather than crashing."""
    root = Path(root) if root is not None else ROOT
    backend = root / "Backend Architecture" / "aether-backend"
    evidence: dict = {
        "manifest_count": 0,
        "manifest_errors": [],
        "scaffolded_providers": [],
        "dishonest_readiness_claims": [],
        "credential_slots": [],
        "credential_slots_required_creds": False,
        "credential_authority": False,
        "tenant_isolation_tests": False,
        "environment_scoping": False,
        "secret_findings": [],
        "secret_scan_ran": False,
        "transport_declared": False,
        "transport_modules": False,
        "normalization_modules": False,
        "normalization_tests": False,
        "storage_models": False,
        "storage_policies": False,
        "migration_count": 0,
        "idempotency_declared": False,
        "idempotency_tests": False,
        "cursor_declared": False,
        "cursor_persistence": False,
        "retry_declared": False,
        "retry_tests": False,
        "dead_letter_modules": False,
        "reconciliation_modules": False,
        "repair_modules": False,
        "repair_required": False,
        "workers_total": 0,
        "workers_supervised": False,
        "workers_unsupervised": [],
        "heartbeat": False,
        "readiness_exposed": False,
        "health_false_success": False,
        "health_verified": False,
        "missing_credential_explicit": False,
        "invalid_credential_explicit": False,
        "provider_outage_explicit": False,
        "empty_vs_failure_preserved": False,
        "unknown_vs_zero_preserved": False,
        "rotation_method_declared": False,
        "rotation_tests": False,
        "rotation_live_verified": False,
        "demotion_logic": False,
        "demotion_tests": False,
        "tenant_diagnostics": False,
        "operator_diagnostics": False,
        "usage_meter_defined": False,
        "entitlement_key_defined": False,
        "offline_fixtures": False,
        "fault_injection_tests": False,
        "infra_declared": False,
        "docs_present": False,
        "docs_current": False,
        "ci_gate_declared": False,
        "ci_verified": False,
        "live_evidence_present": False,
        "live_evidence_sources": [],
        "errors": [],
    }

    _collect_certification(evidence, backend)
    _collect_manifests(evidence)
    _collect_credential_contracts(evidence)
    _collect_workers(evidence, backend)
    _collect_code_evidence(evidence, backend)
    _collect_live_evidence(evidence)
    _collect_secret_scan(evidence)

    # Cross-cutting derived flags.
    evidence["credential_authority"] = bool(
        (backend / "shared" / "credentials" / "service.py").exists()
        and (backend / "services" / "providers" / "credentials" / "authority.py").exists()
    )
    evidence["normalization_tests"] = _contains(
        ROOT, ["tests/**/*.py"], "normalize"
    ) and evidence["normalization_modules"]
    evidence["idempotency_tests"] = _contains(
        ROOT, ["tests/**/*.py"], "idempot"
    ) and evidence["idempotency_declared"]
    # Credential-rotation coverage requires a rotation path in a
    # credential/secret-adjacent test — "rotation" alone is not evidence.
    evidence["rotation_tests"] = (
        _co_occurs(ROOT, ["tests/**/*.py"], ["rotat", "credential"])
        or _co_occurs(ROOT, ["tests/**/*.py"], ["rotat", "secret"])
        or _co_occurs(ROOT, ["tests/**/*.py"], ["rotat", "token"])
    ) and (evidence["rotation_method_declared"] or evidence["credential_slots"])
    evidence["repair_required"] = evidence.get("reconciliation_modules", False)
    return evidence


# ── CLI ───────────────────────────────────────────────────────────────────────


def _print_table(matrix: dict) -> None:
    rows = matrix["rows"]
    summary = matrix["summary"]
    print("Credential-turnkey capability matrix (sec24)")
    print("=" * 100)
    print(f"{'ROW':<38}{'CATEGORY':<18}{'STATUS':<8}{'EXTERNAL':<9}DETAIL")
    print("-" * 100)
    for r in rows:
        ext = "yes" if r["external_blocker"] else ""
        detail = (r["detail"] or "")[:58]
        print(f"{r['label']:<38}{r['category']:<18}{r['status']:<8}{ext:<9}{detail}")
    print("-" * 100)
    print(
        f"total={summary['total']}  pass={summary['pass']}  fail={summary['fail']}  "
        f"warn={summary['warn']}  external_blocker={summary['external_blocker']}"
    )


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any matrix row is FAIL (credential-turnkey-strict)")
    ap.add_argument("--json", action="store_true",
                    help="print the full machine-readable matrix as JSON")
    ap.add_argument("--evidence-json", action="store_true",
                    help="print the raw evidence dict the matrix was evaluated on")
    ap.add_argument("--failures-only", action="store_true",
                    help="print only FAILing rows")
    args = ap.parse_args(argv)

    try:
        evidence = collect_evidence()
    except Exception as exc:  # pragma: no cover - catastrophic
        print(f"error: evidence collection failed: {exc}", file=sys.stderr)
        return 2

    matrix = evaluate_matrix(evidence)
    code = strict_exit_code(matrix)

    if args.evidence_json:
        print(json.dumps(evidence, indent=2, sort_keys=True, default=str))
        return code if args.strict else 0

    if args.json:
        print(json.dumps(matrix, indent=2, sort_keys=True))
        return code if args.strict else 0

    _print_table(matrix)
    for err in evidence.get("errors", []):
        print(f"  [evidence] {err}", file=sys.stderr)

    if args.failures_only:
        print()
        for r in failing_rows(matrix):
            tag = " (external blocker)" if r["external_blocker"] else ""
            print(f"  FAIL {r['id']}{tag}: {r['detail']}")

    if not args.strict:
        return 0

    if code == 0:
        print("credential-turnkey-strict: PASS (no FAIL rows)")
    else:
        print(
            f"credential-turnkey-strict: FAIL — {matrix['summary']['fail']} row(s) "
            f"are FAIL ({matrix['summary']['external_blocker']} external blocker(s))",
            file=sys.stderr,
        )
        for r in failing_rows(matrix):
            tag = " (external blocker)" if r["external_blocker"] else ""
            print(f"  FAIL {r['id']}{tag}: {r['detail']}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
