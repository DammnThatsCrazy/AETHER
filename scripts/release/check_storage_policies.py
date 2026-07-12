#!/usr/bin/env python3
"""Validate the storage policy registry config schema.

This session ships the registry SEED (config/storage_policies.yaml). This gate
validates its schema + coherence: every policy has the required fields and a
declared authoritative store. Full per-resource-type coverage and the object
descriptor layer are a follow-up (ledger FT-7-STORAGE-DESCRIPTORS).

Usage: python scripts/release/check_storage_policies.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard  # noqa: E402

REQUIRED_FIELDS = [
    "resource_type", "authoritative_store", "metadata_store",
    "projection_stores", "codec", "format", "retention_class",
    "delete_behavior", "legal_hold_supported",
]
VALID_DELETE = {"hard_delete", "tombstone", "preserve"}


def check() -> int:
    r = Reporter("STORAGE POLICIES — config/storage_policies.yaml schema")

    try:
        data = load_yaml("config/storage_policies.yaml")
    except FileNotFoundError:
        r.fail("config/storage_policies.yaml not found")
        return r.finish()

    policies = (data or {}).get("policies", [])
    r.require(isinstance(policies, list) and bool(policies),
              "policies list present", "policies list missing or empty")

    seen: set[str] = set()
    for idx, pol in enumerate(policies or []):
        rt = (pol or {}).get("resource_type", f"#{idx}")
        missing = [f for f in REQUIRED_FIELDS if f not in (pol or {})]
        r.require(not missing, f"{rt}: all policy fields present",
                  f"{rt}: missing fields {missing}")

        if rt in seen:
            r.fail(f"{rt}: duplicate resource_type policy")
        seen.add(rt)

        delete = (pol or {}).get("delete_behavior")
        if delete is not None and delete not in VALID_DELETE:
            r.fail(f"{rt}: invalid delete_behavior {delete!r}")

        # Legal/audit data must not be hard-deletable.
        if (pol or {}).get("retention_class") == "legal" and delete == "hard_delete":
            r.fail(f"{rt}: legal retention_class cannot use hard_delete")

    return r.finish()


if __name__ == "__main__":
    main_guard(check)
