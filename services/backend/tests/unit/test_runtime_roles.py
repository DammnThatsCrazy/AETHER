"""Runtime role wiring for the WS5 provider sync scheduler (DECISION 2).

The scheduler rides the existing ``materializer`` role (exact precedent:
``payment_rail_sync`` / ``bronze_object_compaction`` and the Kyber loops) — one
periodic loop does not justify the deploy-profile/compose/Terraform fan-out of a
new runtime role. This module pins that wiring: the spec name is claimed by
``materializer`` (single ownership), ``owning_role`` resolves it, and
``specs_for_role`` routes it to the materializer deployment.
"""

from __future__ import annotations

from services.runtime.roles import (
    ROLE_TO_SPEC_NAMES,
    WORKER_ROLES,
    owning_role,
    specs_for_role,
)
from services.runtime.supervisor import WorkerSpec


def test_provider_sync_scheduler_rides_materializer_role() -> None:
    """WS5-2/WS5-4: the scheduler spec is claimed by the materializer role, so
    it runs wherever materializer runs without a new ``provider-sync-worker``
    role or deployment token."""
    assert "materializer" in WORKER_ROLES
    assert "provider_sync_scheduler" in ROLE_TO_SPEC_NAMES["materializer"]
    # No new role was introduced.
    assert "provider-sync-worker" not in WORKER_ROLES
    assert "provider_sync_scheduler" not in WORKER_ROLES


def test_owning_role_resolves_materializer() -> None:
    assert owning_role("provider_sync_scheduler") == "materializer"


def test_specs_for_role_materializer_includes_scheduler() -> None:
    specs = [
        WorkerSpec(name="payment_rail_sync", factory=lambda: None),
        WorkerSpec(name="provider_sync_scheduler", factory=lambda: None),
        WorkerSpec(name="event_replay", factory=lambda: None),
    ]
    owned = specs_for_role("materializer", specs)
    names = [s.name for s in owned]
    assert "provider_sync_scheduler" in names
    # A spec owned by another role is not leaked into materializer.
    assert "event_replay" not in names


def test_every_spec_has_exactly_one_owner() -> None:
    """The reverse index is built with a single-ownership guard at import; this
    re-asserts it through the public surface so a duplicate claim fails here
    rather than only at import time."""
    seen: dict[str, str] = {}
    for role, spec_names in ROLE_TO_SPEC_NAMES.items():
        for name in spec_names:
            assert name not in seen, f"spec {name!r} claimed by two roles"
            seen[name] = role
    # The scheduler is claimed exactly once (by materializer).
    assert seen["provider_sync_scheduler"] == "materializer"


def test_all_follow_on_spec_names_have_a_role_owner() -> None:
    """Every UPR follow-on spec claimed by a role is resolvable via the reverse
    index — nothing silently dangles unowned."""
    for name in ("provider_sync_scheduler", "payment_rail_sync", "bronze_object_compaction"):
        assert owning_role(name) is not None
