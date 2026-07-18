"""
Aether -- EVM deploy-time safety gates (Python).

Mirrors the JavaScript gates in ``scripts/lib/*`` so the Python multi-chain
deployer enforces the SAME fail-closed rules as ``scripts/deploy.js``:

  1. Mainnet external-audit gate  -> audit/AUDIT_EVIDENCE.json required & valid
  2. Default-key rejection        -> refuse well-known Hardhat/Anvil dev keys
  3. Oracle-signer registry       -> ORACLE_ADDRESS must be allow-listed
  4. Contract-address registry    -> helper for post-deploy verification

Network tiers (fail-closed): anything not explicitly LOCAL or TESTNET is treated
as MAINNET-class and inherits the audit gate.

Raises ``GateError`` on any violation; callers let it propagate so deployment is
aborted (never proceeds past a failed gate).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
#  Paths (this file lives in Smart Contracts/deploy/)
# ---------------------------------------------------------------------------

CONTRACTS_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = CONTRACTS_ROOT / "deploy" / "registry"
ORACLE_REGISTRY_PATH = REGISTRY_DIR / "oracle_signers.json"
CONTRACT_REGISTRY_PATH = REGISTRY_DIR / "contracts.json"
AUDIT_EVIDENCE_PATH = CONTRACTS_ROOT / "audit" / "AUDIT_EVIDENCE.json"

# ---------------------------------------------------------------------------
#  Network classification (kept in sync with scripts/lib/networks.js)
# ---------------------------------------------------------------------------

LOCAL_NETWORKS = {"hardhat", "localhost"}
TESTNET_NETWORKS = {
    "sepolia",
    "amoy",
    "arbitrumSepolia",
    "baseSepolia",
    "optimismSepolia",
}


def is_local_network(name: str) -> bool:
    return name in LOCAL_NETWORKS


def is_testnet_network(name: str) -> bool:
    return name in TESTNET_NETWORKS


def is_mainnet_network(name: str) -> bool:
    """Fail-closed: unknown names are treated as mainnet-class."""
    return not is_local_network(name) and not is_testnet_network(name)


def network_tier(name: str) -> str:
    if is_local_network(name):
        return "LOCAL"
    if is_testnet_network(name):
        return "TESTNET"
    return "MAINNET"


# ---------------------------------------------------------------------------
#  Well-known development keys/addresses denylist
#  (public, universally-known Hardhat/Anvil accounts -- NOT secrets)
# ---------------------------------------------------------------------------

DEFAULT_PRIVATE_KEYS = {
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
    "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
    "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a",
    "0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba",
    "0x92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e",
    "0x4bbbf85ce3377467afe5d46f804f221813b2bb87f24d81f60f1fcdbf7cbf4356",
    "0xdbda1821b80551c9d65939329250298aa3472ba22feea921c0cf5d620ea67b97",
    "0x2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073d0006e7d2a",
}


class GateError(RuntimeError):
    """Raised when a deploy-time safety gate rejects an operation."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


def _norm_key(key: str) -> str:
    k = (key or "").strip().lower()
    if k and not k.startswith("0x"):
        k = "0x" + k
    return k


def _lc(x: Any) -> str:
    return str(x or "").strip().lower()


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(CONTRACTS_ROOT))
    except ValueError:
        return str(p)


# ---------------------------------------------------------------------------
#  Gate 1 -- Mainnet external-audit gate
# ---------------------------------------------------------------------------

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def validate_evidence(ev: dict, audit_dir: Optional[Path] = None) -> list[str]:
    """Return a list of validation errors ([] means valid)."""
    audit_dir = audit_dir or AUDIT_EVIDENCE_PATH.parent
    errors: list[str] = []
    if not isinstance(ev, dict):
        return ["evidence is not a JSON object"]

    auditor = ev.get("auditor") or {}
    report = ev.get("report") or {}
    scope = ev.get("scope") or {}
    signoff = ev.get("signoff") or {}

    if not str(auditor.get("name", "")).strip():
        errors.append("auditor.name is missing/empty")
    sha = str(report.get("sha256", "")).strip()
    if not _HEX64.match(sha):
        errors.append("report.sha256 must be a 64-character hex digest")
    if not str(report.get("file", "")).strip():
        errors.append("report.file is missing/empty")
    if not str(scope.get("commit", "")).strip():
        errors.append("scope.commit is missing/empty")
    contracts = scope.get("contracts")
    if not isinstance(contracts, list) or len(contracts) == 0:
        errors.append("scope.contracts must be a non-empty array")
    if signoff.get("approved") is not True:
        errors.append("signoff.approved must be boolean true")
    if not str(signoff.get("approver", "")).strip():
        errors.append("signoff.approver is missing/empty")

    # If the report file is present on disk, its hash MUST match.
    rfile = str(report.get("file", "")).strip()
    if rfile and _HEX64.match(sha):
        rpath = Path(rfile) if Path(rfile).is_absolute() else audit_dir / rfile
        if rpath.exists():
            digest = hashlib.sha256(rpath.read_bytes()).hexdigest()
            if digest.lower() != sha.lower():
                errors.append(
                    f"report.sha256 mismatch: file {rfile} hashes to {digest} "
                    f"but evidence claims {sha}"
                )
    return errors


def assert_audit_evidence(network: str) -> None:
    """Fail closed on mainnet-class networks without valid audit evidence."""
    if not is_mainnet_network(network):
        return  # testnets + local unaffected

    if not AUDIT_EVIDENCE_PATH.exists():
        raise GateError(
            "AUDIT_GATE",
            f"MAINNET AUDIT GATE: refusing to deploy to '{network}'. No "
            f"external-audit evidence at {_rel(AUDIT_EVIDENCE_PATH)}. Mainnet "
            f"real-value activation stays BLOCKED until a completed audit "
            f"sign-off is recorded there (see audit/AUDIT_EVIDENCE.template.json).",
        )
    try:
        ev = json.loads(AUDIT_EVIDENCE_PATH.read_text())
    except json.JSONDecodeError as exc:
        raise GateError(
            "AUDIT_GATE",
            f"MAINNET AUDIT GATE: {_rel(AUDIT_EVIDENCE_PATH)} is not valid JSON: {exc}",
        )
    errors = validate_evidence(ev)
    if errors:
        joined = "\n  - ".join(errors)
        raise GateError(
            "AUDIT_GATE",
            f"MAINNET AUDIT GATE: audit evidence at {_rel(AUDIT_EVIDENCE_PATH)} "
            f"is invalid for '{network}':\n  - {joined}",
        )


# ---------------------------------------------------------------------------
#  Gate 2 -- Default-key rejection
# ---------------------------------------------------------------------------


def assert_not_default_key(network: str, private_key: str) -> None:
    if is_local_network(network):
        return
    if private_key and _norm_key(private_key) in DEFAULT_PRIVATE_KEYS:
        raise GateError(
            "DEFAULT_KEY",
            f"Refusing to deploy on '{network}': DEPLOYER_KEY is a well-known "
            f"Hardhat/Anvil development key. Use a funded, secret operational "
            f"key supplied via an env/secret reference.",
        )


# ---------------------------------------------------------------------------
#  Gate 3/4 -- Registries
# ---------------------------------------------------------------------------


def _read_json(p: Path) -> Optional[dict]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        raise GateError("REGISTRY", f"Registry file {p} is not valid JSON: {exc}")


def get_registered_oracles(network: str) -> list[str]:
    data = _read_json(ORACLE_REGISTRY_PATH)
    if not data or not isinstance(data.get("networks"), dict):
        return []
    arr = data["networks"].get(network)
    if not isinstance(arr, list):
        return []
    return [_lc(x) for x in arr if _lc(x)]


def assert_oracle_registered(network: str, oracle_address: str) -> None:
    if is_local_network(network):
        return
    allow = get_registered_oracles(network)
    if not allow:
        raise GateError(
            "REGISTRY",
            f"Oracle-signer registry has no entries for network '{network}'. "
            f"Add the authorized oracle address to {_rel(ORACLE_REGISTRY_PATH)} "
            f"under networks.{network} (reviewed change) before deploying.",
        )
    if _lc(oracle_address) not in allow:
        raise GateError(
            "REGISTRY",
            f"Oracle {oracle_address} is NOT registered for network '{network}'. "
            f"Registered: {allow}. Add it to {_rel(ORACLE_REGISTRY_PATH)} "
            f"(reviewed change) or fix ORACLE_ADDRESS.",
        )


def run_evm_predeploy_gates(network: str, oracle_address: str, private_key: str) -> None:
    """Run all pre-deploy EVM gates in order. Raises GateError on the first fail."""
    assert_audit_evidence(network)
    assert_not_default_key(network, private_key)
    assert_oracle_registered(network, oracle_address)
