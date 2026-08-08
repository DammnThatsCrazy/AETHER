#!/usr/bin/env python3
"""Fail closed when a docker-compose file claims the canonical staging profile.

The canonical staging profile (``config/deployment_profiles.yaml``) forbids MSK
(Kafka), ElastiCache (Redis), and self-managed Prometheus/Grafana. A stale
compose stack that provisions all three once lived at ``deploy/staging/`` and
contradicted the profile it claimed to represent. That stack is quarantined
under ``deploy/legacy-staging/`` and must stay there behind a LEGACY marker.

This validator enforces the quarantine and the naming contract:

  1. ``deploy/staging`` must NOT exist — the canonical staging deployment is the
     Terraform root (``profiles/staging.tfvars``), never docker-compose.
  2. Every compose file whose name matches ``*staging*`` must live under
     ``deploy/legacy-staging/`` AND carry the LEGACY marker, so no compose file
     can present itself as the staging profile.
  3. No live operational surface (Makefile, ``.github/workflows/``, ``scripts/``,
     ``config/``) may reference the canonical ``deploy/staging`` path.

Historical changelogs and archived audit docs are exempt by construction: the
scan targets live surfaces only, because those records describe what existed
at the time and are intentionally not rewritten.

Static analysis only; no Terraform binary or AWS credentials required.

Usage: python scripts/release/check_delivery_compose_parity.py
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, main_guard, repo_root  # noqa: E402

# The canonical staging path is reserved for the Terraform root. A directory of
# this name in deploy/ is the drift this validator exists to catch.
DEPLOY_STAGING = "deploy/staging"
LEGACY_STAGING = "deploy/legacy-staging"

# Compose files whose filename carries the staging profile name. Every hit must
# be quarantined under LEGACY_STAGING and carry this marker in its header.
STAGING_COMPOSE_PATTERN = re.compile(r"^.*staging.*\.ya?ml$", re.IGNORECASE)
LEGACY_MARKER = "LEGACY"

# Live surfaces that must never reference the canonical staging path. Archived
# audits (docs/archive/) and changelogs are history, not live ops, and are
# deliberately excluded.
LIVE_SURFACES = (
    "Makefile",
    ".github/workflows",
    "scripts",
    "config",
)

# This validator's own source names the canonical path in its docstring and
# DEPLOY_STAGING constant — it must, to enforce the quarantine. Exclude it from
# the reference scan so the tripwire doesn't trip on itself.
SELF = "scripts/release/check_delivery_compose_parity.py"


def _iter_live_files(root) -> list:
    """Yield repo-relative paths of live operational surfaces."""
    found: list = []
    for rel in LIVE_SURFACES:
        path = root / rel
        if rel == "Makefile":
            if path.exists():
                found.append(rel)
            continue
        if not path.exists():
            continue
        suffixes = (".yml", ".yaml", ".py") if rel in (".github/workflows", "scripts") else (".yaml", ".yml")
        for f in path.rglob("*"):
            if f.is_file() and f.suffix.lower() in suffixes:
                found.append(f.relative_to(root).as_posix())
    return found


def check() -> int:
    r = Reporter("COMPOSE PARITY — no compose file may claim the staging profile")

    root = repo_root()

    # 1. Canonical staging path must not exist in deploy/ ----------------------
    canonical = root / DEPLOY_STAGING
    r.require(
        not canonical.exists(),
        f"{DEPLOY_STAGING} does not exist (canonical staging is Terraform, never docker-compose)",
        f"{DEPLOY_STAGING} exists — the contradicting compose stack must be quarantined "
        f"under {LEGACY_STAGING}/ with a LEGACY marker",
    )

    # 2. Every staging-named compose is quarantined behind the marker ----------
    deploy_dir = root / "deploy"
    staging_composes = []
    if deploy_dir.exists():
        for f in deploy_dir.rglob("*"):
            if f.is_file() and STAGING_COMPOSE_PATTERN.match(f.name):
                staging_composes.append(f.relative_to(root).as_posix())

    quarantine_ok = True
    for rel in staging_composes:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        is_quarantined = rel.startswith(LEGACY_STAGING + "/")
        has_marker = LEGACY_MARKER in text[:2000]
        if not (is_quarantined and has_marker):
            r.fail(
                f"{rel} names the staging profile but is not quarantined: must live under "
                f"{LEGACY_STAGING}/ and carry a '{LEGACY_MARKER}' marker in its header"
            )
            quarantine_ok = False
    if not staging_composes:
        r.warn("no *staging* compose files found under deploy/")
    elif quarantine_ok:
        r.ok(f"all {len(staging_composes)} staging-named compose file(s) quarantined with the LEGACY marker")

    # 3. No live surface references the canonical path --------------------------
    ref_ok = True
    for rel in _iter_live_files(root):
        if rel == SELF:
            continue
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        if DEPLOY_STAGING in text:
            r.fail(f"{rel} references the canonical {DEPLOY_STAGING} path (quarantined; point to {LEGACY_STAGING})")
            ref_ok = False
    if ref_ok:
        r.ok(f"no live surface (Makefile, .github/workflows/, scripts/, config/) references {DEPLOY_STAGING}")

    return r.finish()


if __name__ == "__main__":
    main_guard(check)
