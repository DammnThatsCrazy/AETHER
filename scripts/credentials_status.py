#!/usr/bin/env python3
"""Credential registry status reporter — inventory / preflight / activation-smoke.

Reads the machine-readable credential registry (``config/credential_contracts.yaml``)
and reports the honest provisioning status of every declared credential slot. This is
a **credentialless** reporter: in an environment with no provider secrets it reports
every mobile/notification/distribution slot as ``missing`` (externally blocked) — it
NEVER fabricates an authorized/reachable/ready verdict, and it NEVER prints a secret
value (it checks only presence of a derived environment variable).

Provisioning states (honest, non-overlapping):
  missing       no secret is configured for the slot.
  invalid       the slot's env var is set but empty / whitespace.
  configured    a secret is present (its format/authz/reachability are a LIVE
                preflight concern — not verifiable here).
  untested      configured but not live-verified (preflight/activation-smoke in a
                credentialless env cannot reach the provider → externally blocked).

Modes:
  inventory          enumerate every slot + metadata + present/absent. EXIT 0.
  preflight          per-slot parse/authz posture (no live send). EXIT 0 (report);
                     with --strict, EXIT 1 if a credential REQUIRED for the active
                     deployment profile is missing.
  activation-smoke   per-slot activation posture (no live send in a credentialless
                     env → untested/externally_blocked). EXIT 0. Never "ready".

A green exit is "reported honestly", NEVER "production ready". Credentials-missing is
neither implementation-incomplete nor production-ready.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config" / "credential_contracts.yaml"

# Provisioning states.
MISSING = "missing"
INVALID = "invalid"
CONFIGURED = "configured"
UNTESTED = "untested"


def _env_var_for(secret_reference: str) -> str:
    """Deterministic env var a slot's secret binds to (config-only activation).

    ``byok:notification:apns`` -> ``AETHER_BYOK_NOTIFICATION_APNS``. Presence is
    checked; the VALUE is never read or printed.
    """
    slug = secret_reference.replace(":", "_").replace("-", "_").upper()
    return f"AETHER_{slug}"


def _provisioning_state(secret_reference: str) -> tuple[str, str]:
    """Return (state, env_var_name). Presence-only; never reads the value."""
    name = _env_var_for(secret_reference)
    raw = os.environ.get(name)
    if raw is None:
        return MISSING, name
    if raw.strip() == "":
        return INVALID, name
    return CONFIGURED, name


def _active_profile() -> str:
    return os.environ.get("DEPLOYMENT_PROFILE", "local-live")


def _load_registry() -> dict[str, Any]:
    if not REGISTRY.exists():
        print(f"credential registry not found: {REGISTRY}", file=sys.stderr)
        sys.exit(2)
    with REGISTRY.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _rows(registry: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cred in registry.get("credentials", []):
        state, env_name = _provisioning_state(cred.get("secret_reference", ""))
        rows.append(
            {
                "id": cred.get("id"),
                "provider": cred.get("provider"),
                "capability": cred.get("capability"),
                "required_for_profiles": cred.get("required_for_profiles", []),
                "secret_reference": cred.get("secret_reference"),
                "env_var": env_name,
                "local_fake_present": bool(cred.get("local_fake")) and "n/a" not in str(cred.get("local_fake")).lower(),
                "production_fake_forbidden": bool(cred.get("production_fake_forbidden")),
                "state": state,
            }
        )
    return rows


# ── mode: inventory ──────────────────────────────────────────────────────────

def _inventory(rows: list[dict[str, Any]]) -> int:
    print("Credential registry inventory —", REGISTRY.relative_to(ROOT))
    print("=" * 92)
    print(f"{'ID':<20}{'CAPABILITY':<34}{'STATE':<12}{'FAKE':<6}{'PROFILES'}")
    print("-" * 92)
    for r in rows:
        fake = "yes" if r["local_fake_present"] else "n/a"
        profiles = ",".join(r["required_for_profiles"]) or "-"
        print(f"{r['id']:<20}{r['capability']:<34}{r['state']:<12}{fake:<6}{profiles}")
    print("-" * 92)
    configured = sum(1 for r in rows if r["state"] == CONFIGURED)
    print(f"total={len(rows)}  configured={configured}  missing={sum(1 for r in rows if r['state']==MISSING)}")
    print("NOTE: 'configured' means a secret is present — not that it is valid, "
          "authorized, reachable, or production-ready.")
    return 0


# ── mode: preflight ──────────────────────────────────────────────────────────

def _preflight(rows: list[dict[str, Any]], strict: bool) -> int:
    profile = _active_profile()
    print(f"Credential preflight (no live send) — profile={profile}")
    print("=" * 92)
    blocking: list[str] = []
    for r in rows:
        required = profile in r["required_for_profiles"]
        if r["state"] == MISSING:
            posture = "BLOCKED (missing)" if required else "missing (not required for this profile)"
        elif r["state"] == INVALID:
            posture = "BLOCKED (invalid: empty secret)"
        else:  # configured
            # Live format/authz validation is externally blocked in a credentialless env.
            posture = "untested (configured; live validation externally blocked)"
        marker = "REQUIRED" if required else "optional "
        print(f"  [{marker}] {r['id']:<20} {r['env_var']:<40} -> {posture}")
        if required and r["state"] in (MISSING, INVALID):
            blocking.append(r["id"])
    print("-" * 92)
    if blocking:
        print(f"NOT READY: {len(blocking)} credential(s) required for profile "
              f"'{profile}' are missing/invalid: {', '.join(blocking)}")
        print("externally_blocked != implementation-incomplete != production-ready.")
        if strict:
            return 1
    else:
        print(f"No missing credentials block profile '{profile}'. "
              "(This is not a live validation — reachability/authz remain untested.)")
    return 0


# ── mode: activation-smoke ───────────────────────────────────────────────────

def _activation_smoke(rows: list[dict[str, Any]]) -> int:
    print("Credential activation smoke (rehearsal posture — no live send)")
    print("=" * 92)
    for r in rows:
        if r["state"] == CONFIGURED:
            posture = "untested (would run live activation smoke — externally blocked here)"
        else:
            posture = "externally_blocked (no credential to activate)"
        print(f"  {r['id']:<20} {r['capability']:<34} -> {posture}")
    print("-" * 92)
    print("No live provider send is performed in a credentialless environment. "
          "A slot is NEVER reported 'ready' from this tool.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["inventory", "preflight", "activation-smoke"],
                    default="inventory")
    ap.add_argument("--strict", action="store_true",
                    help="preflight: EXIT 1 if a credential required for the active profile is missing")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON and exit 0")
    args = ap.parse_args()

    registry = _load_registry()
    rows = _rows(registry)

    if args.json:
        print(json.dumps({"mode": args.mode, "profile": _active_profile(), "credentials": rows}, indent=2))
        return 0

    if args.mode == "inventory":
        return _inventory(rows)
    if args.mode == "preflight":
        return _preflight(rows, args.strict)
    return _activation_smoke(rows)


if __name__ == "__main__":
    sys.exit(main())
