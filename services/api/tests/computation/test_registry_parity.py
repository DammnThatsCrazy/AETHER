"""Registry governance tests: the generated twin matches the hand-authored
registry, and every active definition is owned and tested."""

from __future__ import annotations

import json

from shared.computation.definition import LifecycleState
from shared.computation.generated_registry import GENERATED_DEFINITIONS, REGISTRY_DIGEST
from shared.computation.registry import list_definitions


def _snapshot() -> list[dict]:
    defs = [d.model_dump(mode="json") for d in list_definitions()]
    defs.sort(key=lambda d: (d["definition_id"], d["definition_version"]))
    return defs


def test_generated_registry_matches_source():
    live = _snapshot()
    assert live == GENERATED_DEFINITIONS, (
        "generated_registry.py is stale — run "
        "`python scripts/generate_computation_registry.py`"
    )


def test_generated_digest_is_consistent():
    import hashlib

    payload = json.dumps(GENERATED_DEFINITIONS, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert digest == REGISTRY_DIGEST


def test_active_definitions_have_owner_and_tests():
    for d in list_definitions():
        if d.lifecycle_state == LifecycleState.ACTIVE:
            assert d.owner and d.owner.strip(), f"{d.key()} has no owner"
            assert d.tests, f"{d.key()} declares no tests"


def test_definition_ids_are_unique():
    keys = [d.key() for d in list_definitions()]
    assert len(keys) == len(set(keys))
