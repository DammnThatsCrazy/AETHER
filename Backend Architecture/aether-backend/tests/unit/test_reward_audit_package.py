"""
Audit-package completeness + mainnet-gate honesty tests (A6 / program sec18, 3F).

Asserts two things about the external-audit readiness package under
``Smart Contracts/audit/``:

1. **Completeness** — every artifact the external auditor and the deploy-time
   gate need is present: the evidence manifest template, the code-review
   checklist, the deployment-guards summary, scope/threat-model/invariants,
   reproducible build + captured Slither output, and the finding template.

2. **Honesty** — NOTHING is fabricated:
   - ``audit/AUDIT_EVIDENCE.json`` (the file that actually unblocks mainnet)
     does NOT exist at this build state; only the ``...template.json`` exists and
     its ``signoff.approved`` is ``false``.
   - Both deploy-time gates (``deploy/evm_guards.py`` and
     ``scripts/lib/audit_gate.js``) reference the evidence file and fail closed
     on mainnet-class networks — verified by running the Python gate's
     ``validate_evidence`` against the template and asserting it is REJECTED.
   - The backend EVM-mainnet activation gate (``services/rewards/onchain_gate.py``)
     refuses activation without recorded evidence.

This is a staging-readiness assertion: it pins that mainnet real-value stays
BLOCKED until a human records a real, completed audit sign-off. When a genuine
audit completes and ``AUDIT_EVIDENCE.json`` is added, the ``test_no_fabricated_evidence``
assertion must be updated deliberately alongside that reviewed change.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# Repo root: <pkg>/tests/unit → up 4 to the monorepo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACTS_ROOT = _REPO_ROOT / "Smart Contracts"
AUDIT_DIR = CONTRACTS_ROOT / "audit"
BACKEND_REPO = _REPO_ROOT / "Backend Architecture" / "aether-backend"

# Every artifact the external-audit package must ship.
REQUIRED_AUDIT_FILES: tuple[str, ...] = (
    "README.md",                       # package overview + how the gate works
    "SCOPE.md",                        # exact in/out-of-scope files + commit
    "ARCHITECTURE.md",                 # components, actors, data flow
    "THREAT_MODEL.md",                 # assets, adversaries, mitigations
    "TRUST_ASSUMPTIONS.md",            # privileged roles + trust boundaries
    "STATE_TRANSITIONS.md",            # contract/campaign state machines
    "INVARIANTS.md",                   # properties that must always hold
    "EIP712_SIGNATURE_SPEC.md",        # signature scheme / domain separation
    "TEST_PLAN.md",                    # test inventory + commands
    "DEPLOYMENT.md",                   # deploy/verify + runbooks
    "DEPLOYMENT_GUARDS.md",            # summary of the fail-closed deploy gates
    "CODE_REVIEW_CHECKLIST.md",        # what the external auditor must verify
    "KNOWN_LIMITATIONS.md",            # accepted limitations / trade-offs
    "SLITHER.md",                      # how to run + interpret Slither
    "slither-output.txt",              # captured Slither run output
    "DEPENDENCIES.md",                 # pinned toolchain + libraries
    "REPRODUCIBLE_BUILD.md",           # deterministic build + reproduction
    "AUDIT_FINDING_TEMPLATE.md",       # issue template for reporting findings
    "AUDIT_EVIDENCE.template.json",    # sign-off shape (never the sign-off itself)
)

# Files that would OPEN the mainnet gate if fabricated. Only the template may
# exist pre-audit.
EVIDENCE_FILE = AUDIT_DIR / "AUDIT_EVIDENCE.json"
EVIDENCE_TEMPLATE = AUDIT_DIR / "AUDIT_EVIDENCE.template.json"


def _load_py_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ═══════════════════════════════════════════════════════════════════════════
# 1. package completeness
# ═══════════════════════════════════════════════════════════════════════════

def test_audit_package_has_all_required_artifacts():
    assert AUDIT_DIR.is_dir(), f"audit package missing at {AUDIT_DIR}"
    missing = [f for f in REQUIRED_AUDIT_FILES if not (AUDIT_DIR / f).is_file()]
    assert not missing, f"audit package is missing artifacts: {missing}"


def test_evidence_manifest_template_documents_required_fields():
    payload = json.loads(EVIDENCE_TEMPLATE.read_text())
    auditor = payload.get("auditor", {})
    report = payload.get("report", {})
    scope = payload.get("scope", {})
    signoff = payload.get("signoff", {})
    # Fields the deploy-time gate validates must be documented.
    assert "name" in auditor
    assert "sha256" in report
    assert "file" in report
    assert "commit" in scope
    assert "contracts" in scope
    assert "approved" in signoff
    assert "approver" in signoff
    # And the template explicitly instructs that approved stays false.
    assert signoff.get("approved") is False


def test_code_review_checklist_is_substantive():
    checklist = (AUDIT_DIR / "CODE_REVIEW_CHECKLIST.md").read_text()
    # Must enumerate verifiable, auditor-actionable items (not a stub).
    for section in ("eip", "nonce", "replay", "oracle", "withdraw", "cap", "access"):
        assert section in checklist.lower(), f"checklist missing '{section}' coverage"


def test_deployment_guards_summary_documents_gates():
    guards = (AUDIT_DIR / "DEPLOYMENT_GUARDS.md").read_text()
    # Both the JS and Python deploy gates plus the backend activation gate.
    assert "audit_gate.js" in guards
    assert "evm_guards.py" in guards
    assert "onchain_gate" in guards


# ═══════════════════════════════════════════════════════════════════════════
# 2. mainnet gate honesty (nothing fabricated)
# ═══════════════════════════════════════════════════════════════════════════

def test_no_fabricated_audit_evidence():
    """The file that unblocks mainnet must NOT exist until a real audit sign-off.

    A deliberately-reviewed change is required before adding it (see module
    docstring) — this is the honesty guardrail for the pre-staging package.
    """
    assert not EVIDENCE_FILE.exists(), (
        f"AUDIT_EVIDENCE.json must not be fabricated pre-audit: {EVIDENCE_FILE}"
    )


def test_evidence_template_does_not_open_the_gate():
    """Running the real Python deploy gate against the template must REJECT it."""
    evm_guards = _load_py_module("evm_guards", CONTRACTS_ROOT / "deploy" / "evm_guards.py")
    payload = json.loads(EVIDENCE_TEMPLATE.read_text())
    errors = evm_guards.validate_evidence(payload)
    assert errors, "template must be rejected by the deploy gate (approved=false)"
    # Every missing/empty sign-off field the gate cares about is reported.
    assert any("signoff.approved" in e for e in errors)


def test_evm_guards_py_fails_closed_on_mainnet_without_evidence():
    evm_guards = _load_py_module("evm_guards", CONTRACTS_ROOT / "deploy" / "evm_guards.py")
    with pytest.raises(evm_guards.GateError) as exc:
        evm_guards.assert_audit_evidence("ethereum")
    assert exc.value.category == "AUDIT_GATE"
    assert "MAINNET" in str(exc.value)


def test_audit_gate_js_fails_closed_on_mainnet_without_evidence():
    src = (CONTRACTS_ROOT / "scripts" / "lib" / "audit_gate.js").read_text()
    assert "AUDIT_EVIDENCE.json" in src
    assert "assertAuditEvidence" in src
    assert "isMainnetNetwork" in src
    assert "No external-audit" in src  # fail-closed messaging present


def test_backend_onchain_gate_requires_evidence_on_mainnet():
    gate = (BACKEND_REPO / "services" / "rewards" / "onchain_gate.py").read_text()
    assert "assert_mainnet_audit_evidence" in gate
    assert "MainnetAuditRequiredError" in gate
    assert "find_active" in gate  # real evidence lookup, not a stub
    # The gate must be exercised by an existing test (never a silent no-op).
    assert (BACKEND_REPO / "tests" / "unit" / "test_reward_onchain_gate.py").is_file()


def test_gate_reference_drift_between_js_and_python():
    """Both deploy gates must point at the SAME evidence path."""
    py_src = (CONTRACTS_ROOT / "deploy" / "evm_guards.py").read_text()
    js_src = (CONTRACTS_ROOT / "scripts" / "lib" / "audit_gate.js").read_text()
    assert "audit" + os.sep + "AUDIT_EVIDENCE.json" in py_src.replace("\\", os.sep)
    assert "AUDIT_EVIDENCE.json" in js_src
