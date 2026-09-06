#!/usr/bin/env python3
"""SDK version-compatibility tier gate (Gate H — Compatibility / WS-E 6).

Fail-closed, static, no-backend-import validator encoding the Invariant #18
tier table + the staged (shadow/observe) conformance contract for the
``services/ingestion/sdk_version_tiers.py`` model:

Gate H compatibility — previous supported SDK versions continue functioning:
  * 8.x stays ``supported`` (full capability set, open upper bound);
  * 7.x stays ``deprecated`` — still fully served with the SAME full capability
    set, never blocked;
  * 6.x stays ``read_compatible`` — flat SDK submission still ingests
    (batch/server-side/replay), never blocked;
  * 5.x is ``blocked`` ONLY after its declared blocked-after date (enforcement
    is fail-closed by DATE, never by band alone) — moving the date into the
    past, or turning a served band into a blocker before its date, fails this
    gate;
  * <5.0 is ``unsupported``/advisory — never an ingress blocker by itself;
  * an unparseable/unknown version resolves to ``unclassified`` and NEVER
    blocks;
  * every band capability references a declared canonical capability id (no
    ad-hoc capability strings).

Staged conformance — every WS-E mechanism ships behind a NEW default-OFF flag:
  * ``AETHER_INGESTION_OBSERVABILITY_ENABLED`` defaults False;
  * ``AETHER_SDK_VERSION_COMPAT_ENABLED`` defaults False;
  * ``AETHER_SDK_VERSION_COMPAT_MODE`` defaults ``"off"`` (advisory ladder:
    off -> shadow/warn -> enforce);
  * all three are declared in BOTH ``.env.example`` and ``.env.production.example``.

Exit code 0 = all checks pass; exit code 1 fails the repo-doctor gate.
"""
from __future__ import annotations

import ast
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "Backend Architecture", "aether-backend")
TIERS_PY = os.path.join(BACKEND, "services", "ingestion", "sdk_version_tiers.py")
SETTINGS_PY = os.path.join(BACKEND, "config", "settings.py")
ENV_EXAMPLE = os.path.join(ROOT, ".env.example")
ENV_PROD_EXAMPLE = os.path.join(ROOT, ".env.production.example")

ERRORS: list[str] = []
NOTES: list[str] = []

# Expected canonical capability ids (must exist as CAP_* string constants).
EXPECTED_CAPS = {
    "batch_ingestion",
    "server_side_ingestion",
    "canonical_observation_envelope",
    "normalization_spine",
    "idempotent_replay",
}
# Full-caps bands (still fully served) vs flat-caps bands (pre-Envelope-B).
FULL_CAPS_BANDS = {"supported", "deprecated"}
FLAT_CAPS_BANDS = {"read_compatible", "blocked"}


def fail(msg: str) -> None:
    ERRORS.append(msg)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _collect_consts(tree: ast.Module):
    """Map module-level constants for capability/date analysis.

    Returns ``(str_consts, set_consts)`` where ``str_consts`` maps
    ``NAME = "literal"`` assignments (the CAP_* ids) and ``set_consts`` maps
    ``NAME = ("a", "b")`` / ``NAME = OTHER_SET`` tuple assignments (the
    ``_CAPS_*`` capability sets) to expanded string sets.
    """
    str_consts: dict[str, str] = {}
    set_consts: dict[str, set[str]] = {}

    def expand(value: ast.expr) -> set[str]:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return {value.value}
        if isinstance(value, ast.Tuple):
            out: set[str] = set()
            for elt in value.elts:
                out |= expand(elt)
            return out
        if isinstance(value, ast.Name):
            name = value.id
            if name in str_consts:
                return {str_consts[name]}
            if name in set_consts:
                return set(set_consts[name])
        return set()

    def record(target: str, value: ast.expr) -> None:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            str_consts[target] = value.value
        elif isinstance(value, ast.Tuple) or isinstance(value, ast.Name):
            set_consts[target] = expand(value)

    def walk(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node.target, ast.Name):
                    targets = [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        record(target.id, node.value)

    walk(tree.body)
    return str_consts, set_consts


def _check_tier_table() -> None:
    if not os.path.exists(TIERS_PY):
        fail(f"missing tier module: {os.path.relpath(TIERS_PY, ROOT)}")
        return
    tree = ast.parse(_read(TIERS_PY))

    str_consts, set_consts = _collect_consts(tree)
    known_caps = {v for v in str_consts.values() if v in EXPECTED_CAPS}
    for cap in EXPECTED_CAPS:
        if cap not in known_caps:
            fail(f"capability id {cap!r} must be declared as a CAP_* string constant")

    # Module-level date constants (Assign or AnnAssign).
    blocked_after = None
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        if isinstance(target, ast.Name) and target.id == "BLOCKED_AFTER_DATE" \
                and isinstance(node.value, ast.Constant):
            blocked_after = str(node.value.value)
    if blocked_after is None:
        fail("BLOCKED_AFTER_DATE must be declared in sdk_version_tiers.py")
        blocked_after = "2030-01-01"

    # Parse the SDK_VERSION_BANDS tuple of SdkVersionBand(...) calls
    # (declared as an annotated module assignment).
    def caps_of(value: ast.expr) -> set[str]:
        if isinstance(value, ast.Tuple):
            out: set[str] = set()
            for elt in value.elts:
                out |= caps_of(elt)
            return out
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return {value.value}
        if isinstance(value, ast.Name) and value.id in set_consts:
            return set(set_consts[value.id])
        return set()

    bands: dict[str, dict[str, object]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        if not (isinstance(target, ast.Name) and target.id == "SDK_VERSION_BANDS"):
            continue
        if not isinstance(node.value, ast.Tuple):
            continue
        for elt in node.value.elts:
            if not (isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name)
                    and elt.func.id == "SdkVersionBand"):
                continue
            kwargs: dict[str, object] = {}
            for kw in elt.keywords:
                if kw.arg is None:
                    continue
                val: object
                if isinstance(kw.value, ast.Constant):
                    val = kw.value.value
                elif kw.arg == "capabilities":
                    val = caps_of(kw.value)
                elif isinstance(kw.value, ast.Name) and kw.value.id in str_consts:
                    val = str_consts[kw.value.id]  # reference to a string constant
                elif isinstance(kw.value, ast.Name):
                    val = ("REF", kw.value.id)
                elif isinstance(kw.value, ast.Tuple):
                    items = [
                        el.value for el in kw.value.elts
                        if isinstance(el, ast.Constant) and isinstance(el.value, str)
                    ]
                    val = items
                else:
                    val = None
                kwargs[kw.arg] = val
            band_id = kwargs.get("id")
            if isinstance(band_id, str):
                bands[band_id] = kwargs

    for expected in ("supported", "deprecated", "read_compatible", "blocked", "unsupported"):
        if expected not in bands:
            fail(f"SDK_VERSION_BANDS missing required band {expected!r}")

    def get(band: dict[str, object], key: str):
        return band.get(key)

    # 8.x supported: min 8.0.0, open upper bound.
    sup = bands.get("supported", {})
    if get(sup, "min_version") != "8.0.0":
        fail("supported band must start at 8.0.0")
    if get(sup, "max_version_exclusive") is not None:
        fail("supported band must have an open upper bound (never capped)")
    # 7.x deprecated: still fully served between 7.0.0 and 8.0.0.
    dep = bands.get("deprecated", {})
    if get(dep, "min_version") != "7.0.0" or get(dep, "max_version_exclusive") != "8.0.0":
        fail("deprecated (7.x) band must cover [7.0.0, 8.0.0)")
    if get(dep, "blocked_after") not in (None, ""):
        fail("deprecated (7.x) band must never be date-blocked")
    # 6.x read_compatible: flat submission still works.
    rc = bands.get("read_compatible", {})
    if get(rc, "min_version") != "6.0.0" or get(rc, "max_version_exclusive") != "7.0.0":
        fail("read_compatible (6.x) band must cover [6.0.0, 7.0.0)")
    if get(rc, "blocked_after") not in (None, ""):
        fail("read_compatible (6.x) band must never be date-blocked")
    # 5.x blocked after date only.
    blk = bands.get("blocked", {})
    if get(blk, "min_version") != "5.0.0" or get(blk, "max_version_exclusive") != "6.0.0":
        fail("blocked (5.x) band must cover [5.0.0, 6.0.0)")
    if get(blk, "blocked_after") != blocked_after:
        fail("blocked (5.x) band must be blocked only after BLOCKED_AFTER_DATE")
    # <5.0 unsupported — advisory only, open lower bound.
    uns = bands.get("unsupported", {})
    if get(uns, "min_version") is not None or get(uns, "max_version_exclusive") != "5.0.0":
        fail("unsupported (<5.0) band must be open-lower, capped exclusively at 5.0.0")

    # Capability-set conformance: full vs flat, and ids must be canonical.
    for band_id, band in bands.items():
        caps_arg = band.get("capabilities")
        if isinstance(caps_arg, set):
            cap_ids = caps_arg
        elif isinstance(caps_arg, (list, tuple)):
            cap_ids = set(caps_arg)
        else:
            cap_ids = set()
        for cap in cap_ids:
            if cap not in EXPECTED_CAPS:
                fail(f"band {band_id!r} references non-canonical capability {cap!r}")
        if band_id in FULL_CAPS_BANDS:
            missing = EXPECTED_CAPS - cap_ids
            if missing:
                fail(f"{band_id} band must carry the FULL capability set (missing {sorted(missing)})")
        elif band_id in FLAT_CAPS_BANDS:
            flat = {"batch_ingestion", "server_side_ingestion", "idempotent_replay"}
            if not flat <= cap_ids:
                fail(f"{band_id} band must keep flat submission capabilities "
                     f"ingesting (missing {sorted(flat - cap_ids)})")
            if "canonical_observation_envelope" in cap_ids:
                fail(f"{band_id} band must NOT claim Envelope-B (flat pre-Envelope-B band)")
        elif band_id == "unsupported":
            if cap_ids:
                fail("unsupported band must carry NO capabilities")

    # Blocked-after date must stay in the future (fail-closed by date).
    try:
        today_iso = datetime.now(timezone.utc).date().isoformat()
    except Exception:  # pragma: no cover - date is always available
        today_iso = "2030-01-01"
    if blocked_after <= today_iso:
        fail(f"BLOCKED_AFTER_DATE {blocked_after} has arrived — enforcement would "
             "block live 5.x clients (compatibility regression)")
    NOTES.append(f"BLOCKED_AFTER_DATE = {blocked_after} (future; current tree never blocks)")

    # UNCLASSIFIED sentinel must never block (both bounds open).
    if not os.path.exists(TIERS_PY):
        return
    source = _read(TIERS_PY)
    if "min_version=None,\n    max_version_exclusive=None,\n    blocked_after=None" not in source \
            and "id=\"unclassified\"" not in source:
        fail("unclassified sentinel band must exist with open bounds + no block date")


def _check_staged_flags() -> None:
    """Every WS-E mechanism ships behind a NEW default-OFF env flag."""
    if not os.path.exists(SETTINGS_PY):
        fail(f"missing settings: {os.path.relpath(SETTINGS_PY, ROOT)}")
        return
    settings_source = _read(SETTINGS_PY)
    required_settings = [
        ('_env_bool("AETHER_INGESTION_OBSERVABILITY_ENABLED", False)', "observability flag defaults OFF"),
        ('_env_bool("AETHER_SDK_VERSION_COMPAT_ENABLED", False)', "version-compat flag defaults OFF"),
        ('_env("AETHER_SDK_VERSION_COMPAT_MODE", "off")', "version-compat mode defaults off"),
    ]
    for needle, desc in required_settings:
        if needle not in settings_source:
            fail(f"settings.py missing {desc}: expected literal {needle}")

    for env_path in (ENV_EXAMPLE, ENV_PROD_EXAMPLE):
        if not os.path.exists(env_path):
            fail(f"missing env example: {os.path.relpath(env_path, ROOT)}")
            continue
        text = _read(env_path)
        for var in ("AETHER_INGESTION_OBSERVABILITY_ENABLED",
                    "AETHER_SDK_VERSION_COMPAT_ENABLED",
                    "AETHER_SDK_VERSION_COMPAT_MODE"):
            if var not in text:
                fail(f"{os.path.basename(env_path)} must declare {var}")
    NOTES.append("WS-E flags declared default OFF / off in settings + both env examples")


def main() -> int:
    _check_tier_table()
    _check_staged_flags()
    print("SDK version-compatibility tier gate (Gate H — Compatibility)")
    for note in NOTES:
        print(f"  note: {note}")
    if ERRORS:
        print("ERRORS:")
        for e in ERRORS:
            print(f"  - {e}")
        return 1
    print("PASSED -- tier table preserves supported/deprecated/read-compatible bands; "
          "enforcement staged behind default-OFF flags; WS-E flags registered in env examples.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
