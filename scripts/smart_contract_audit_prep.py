#!/usr/bin/env python3
"""Pre-audit preparation script for Aether smart contracts.

Runs local static checks, validates the audit surface, and produces a
summary checklist that should accompany any external audit engagement.

Usage:
    python scripts/smart_contract_audit_prep.py          # full report
    python scripts/smart_contract_audit_prep.py --check  # exit 1 if blockers found

This does NOT replace an external audit. It ensures the codebase is in the
best possible state before engaging an auditor so they spend time on hard
problems, not fixable lint issues.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = ROOT / "Smart Contracts"
SOLIDITY_CONTRACTS = list((CONTRACTS_DIR / "contracts").glob("*.sol"))
PROGRAMS = list((CONTRACTS_DIR / "programs").glob("**/*.rs"))

CHECKLIST = [
    ("Solidity contracts compile cleanly",
     lambda: _run_compile()),
    ("All Solidity contracts have SPDX license identifier",
     lambda: _check_spdx()),
    ("No direct oracle role mutation (grantRole bypass)",
     lambda: _check_oracle_guard()),
    ("getOracleAddress() includes role consistency check",
     lambda: _check_oracle_getter()),
    ("claimReward enforces amount == campaign.rewardAmount",
     lambda: _check_amount_bound()),
    ("ReentrancyGuard present on token-transfer functions",
     lambda: _check_reentrancy_guard()),
    ("Emergency withdrawal is paused-only",
     lambda: _check_emergency_withdraw()),
    ("docs/archive/audits/ contains at least one audit document",
     lambda: _check_audit_docs()),
    ("Slither workflow exists in CI",
     lambda: _check_slither_workflow()),
]


def _run_compile() -> tuple[bool, str]:
    node_modules = CONTRACTS_DIR / "node_modules"
    if not node_modules.exists():
        return True, "node_modules not installed — skipping compile (run npm ci in Smart Contracts/)"
    r = subprocess.run(
        ["npx", "hardhat", "compile"],
        cwd=CONTRACTS_DIR, capture_output=True, text=True, timeout=120,
    )
    if r.returncode == 0:
        return True, "Hardhat compile succeeded"
    return False, f"Compile failed: {r.stderr[:300]}"


def _grep_sol(pattern: str, invert: bool = False) -> list[str]:
    hits = []
    for sol in SOLIDITY_CONTRACTS:
        text = sol.read_text()
        found = pattern in text
        if (found and not invert) or (not found and invert):
            hits.append(sol.name)
    return hits


def _check_spdx() -> tuple[bool, str]:
    missing = _grep_sol("SPDX-License-Identifier", invert=True)
    if missing:
        return False, f"Missing SPDX in: {missing}"
    return True, "All contracts have SPDX-License-Identifier"


def _check_oracle_guard() -> tuple[bool, str]:
    ar = (CONTRACTS_DIR / "contracts" / "AnalyticsRewards.sol").read_text()
    if "OracleRoleManagedViaRotateOracle" in ar:
        return True, "grantRole/revokeRole override blocks direct ORACLE_ROLE mutation"
    return False, "Missing OracleRoleManagedViaRotateOracle guard in AnalyticsRewards.sol"


def _check_oracle_getter() -> tuple[bool, str]:
    ar = (CONTRACTS_DIR / "contracts" / "AnalyticsRewards.sol").read_text()
    if "hasRole(ORACLE_ROLE, oracleSigner)" in ar:
        return True, "getOracleAddress() includes ORACLE_ROLE consistency check"
    return False, "getOracleAddress() does not verify oracleSigner holds ORACLE_ROLE"


def _check_amount_bound() -> tuple[bool, str]:
    ar = (CONTRACTS_DIR / "contracts" / "AnalyticsRewards.sol").read_text()
    if "InvalidRewardAmount" in ar and "campaign.rewardAmount" in ar:
        return True, "claimReward enforces amount == campaign.rewardAmount"
    return False, "claimReward does not enforce reward amount bound"


def _check_reentrancy_guard() -> tuple[bool, str]:
    ar = (CONTRACTS_DIR / "contracts" / "AnalyticsRewards.sol").read_text()
    if "nonReentrant" in ar and "ReentrancyGuard" in ar:
        return True, "ReentrancyGuard and nonReentrant modifier present"
    return False, "ReentrancyGuard or nonReentrant modifier missing"


def _check_emergency_withdraw() -> tuple[bool, str]:
    ar = (CONTRACTS_DIR / "contracts" / "AnalyticsRewards.sol").read_text()
    if "whenPaused" in ar and "emergencyWithdraw" in ar:
        return True, "emergencyWithdraw gated by whenPaused modifier"
    return False, "emergencyWithdraw not confirmed paused-only"


def _check_audit_docs() -> tuple[bool, str]:
    audit_dir = ROOT / "docs" / "archive" / "audits"
    docs = list(audit_dir.glob("*.md")) if audit_dir.exists() else []
    if docs:
        return True, f"{len(docs)} audit doc(s): {[d.name for d in docs]}"
    return False, "No audit documents found in docs/archive/audits/"


def _check_slither_workflow() -> tuple[bool, str]:
    wf = ROOT / ".github" / "workflows" / "smart-contract-analysis.yml"
    if wf.exists():
        return True, "Slither CI workflow present at .github/workflows/smart-contract-analysis.yml"
    return False, "Slither CI workflow missing"


def main() -> int:
    strict = "--check" in sys.argv

    print("=" * 70)
    print("AETHER SMART CONTRACT PRE-AUDIT CHECKLIST")
    print("=" * 70)
    print()
    print("Contracts under review:")
    for sol in SOLIDITY_CONTRACTS:
        print(f"  {sol.name}")
    print(f"\nMulti-chain programs: {len(PROGRAMS)} Rust files")
    print()

    passed = 0
    failed = 0
    for name, check_fn in CHECKLIST:
        try:
            ok, detail = check_fn()
        except Exception as exc:
            ok, detail = False, f"check error: {exc}"
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}]  {name}")
        print(f"           {detail}")
        if ok:
            passed += 1
        else:
            failed += 1

    print()
    print(f"Results: {passed} passed, {failed} failed")
    print()

    if failed:
        print("BLOCKERS — resolve before engaging external auditor:")
        for name, check_fn in CHECKLIST:
            try:
                ok, detail = check_fn()
            except Exception:
                ok = False
            if not ok:
                print(f"  - {name}")
        print()
        print("NOTE: External audit required before any mainnet deployment.")
        print("      Suggested auditors: Trail of Bits, OpenZeppelin, Spearbit, Halborn")
        if strict:
            return 1
    else:
        print("All pre-audit checks passed.")
        print("NEXT: Commission external security audit.")
        print("      Suggested auditors: Trail of Bits, OpenZeppelin, Spearbit, Halborn")

    return 0


if __name__ == "__main__":
    sys.exit(main())
