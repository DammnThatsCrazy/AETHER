#!/usr/bin/env python3
"""Validate the signal-use policy matrix against the consent registry.

Enforces the tenant-safety invariants (no broad-consent fallback for sensitive
signals; fingerprint-only never links; explicit opt-in signals require their
exact explicit-opt-in purpose):

  - every signal declares at least one required_purpose;
  - every required_purpose is a real key in consent-registry.json;
  - explicit_opt_in_required signals map to EXACTLY their explicit-opt-in purpose
    (no fallback / OR of multiple purposes);
  - device_fingerprint never allows identity linking.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "packages" / "shared" / "contracts" / "signal-use-matrix.json"
CONSENT = ROOT / "packages" / "shared" / "contracts" / "consent-registry.json"

ERRORS: list[str] = []


def fail(msg: str) -> None:
    ERRORS.append(msg)


def main() -> int:
    if not MATRIX.exists():
        fail(f"missing {MATRIX.relative_to(ROOT)}")
        return _report()
    matrix = json.loads(MATRIX.read_text())
    consent = json.loads(CONSENT.read_text())

    purposes = {p["key"] for p in consent["purposes"]}
    explicit = {p["key"] for p in consent["purposes"] if p.get("explicitOptInRequired")}

    seen: set[str] = set()
    for sig in matrix["signals"]:
        st = sig.get("signal_type", "<unknown>")
        if st in seen:
            fail(f"duplicate signal_type {st}")
        seen.add(st)

        req = sig.get("required_purposes") or []
        if not req:
            fail(f"{st}: required_purposes must be non-empty (no broad-consent fallback)")
        for p in req:
            if p not in purposes:
                fail(f"{st}: required_purpose {p!r} is not in consent-registry.json")

        if sig.get("explicit_opt_in_required"):
            # Sensitive signals require EXACTLY their explicit-opt-in purpose.
            if len(req) != 1 or req[0] not in explicit:
                fail(
                    f"{st}: explicit_opt_in signal must require exactly one explicit "
                    f"opt-in purpose (got {req})"
                )
        else:
            # A non-sensitive signal must not silently require an explicit purpose.
            for p in req:
                if p in explicit:
                    fail(f"{st}: non-sensitive signal must not require explicit opt-in purpose {p!r}")

        if st == "device_fingerprint" and sig.get("allow_identity_linking") is not False:
            fail("device_fingerprint must set allow_identity_linking=false (fingerprint-only never links)")

    return _report()


def _report() -> int:
    if ERRORS:
        print("signal-use matrix validation FAILED:")
        for e in ERRORS:
            print(f"  - {e}")
        return 1
    print("signal-use matrix validation OK (purposes valid; sensitive signals require exact opt-in).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
