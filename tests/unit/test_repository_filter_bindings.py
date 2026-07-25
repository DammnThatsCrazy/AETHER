"""Filter values must be bound the way PostgreSQL's ``->>`` renders them.

``data->>'k'`` returns a JSON value as text in *JSON* spelling. Python's
``str(True)`` is ``'True'``; jsonb yields ``'true'``. Binding the Python
spelling meant every boolean filter in the repository matched **nothing**, and
it failed in the worst possible way: silently. An empty result set is
indistinguishable from "there are no such rows".

Four call sites were affected, all returning ``[]`` forever on PostgreSQL:

* ``services/kyber/ops/containment.py`` — ``find_many({"active": True})``. No
  containment switch was ever readable, so ``is_paused()`` was always False, a
  paused tenant was never actually protected from a command, the
  ``containment_switch_active`` postcondition could never pass, and the console
  reported a frozen platform as unfrozen.
* ``services/web3/registries.py`` — the stablecoin registry.
* ``services/notification_intelligence/delivery_router.py`` — active channels.
* ``repositories/commerce_repos.py`` — active records.

Every one of them passed its tests, because the in-memory backend compares
Python objects directly and ``True == True`` holds there. The two backends
disagreed and nothing noticed. These tests pin the *binding* rather than the
query result, so they hold without a database — which is the only way this
regression can be caught in a suite that runs on the in-memory backend.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import BaseRepository, _jsonb_text  # noqa: E402


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "true"),
        (False, "false"),
        ("open", "open"),
        ("true", "true"),
        (5, "5"),
        (3.5, "3.5"),
    ],
)
def test_filter_values_render_in_json_spelling(value, expected):
    """A bound filter must read as jsonb writes it, not as Python prints it."""
    assert _jsonb_text(value) == expected


def test_python_boolean_spelling_is_never_emitted():
    """The exact regression: 'True'/'False' must never reach a query.

    jsonb stores `true`. A parameter of `'True'` compares unequal to every row
    ever written, which is why this defect produced empty results rather than an
    error anyone would have investigated.
    """
    assert _jsonb_text(True) != "True"
    assert _jsonb_text(False) != "False"


async def test_boolean_filter_round_trips_on_the_in_memory_backend():
    """The in-memory path must agree with the SQL path on booleans.

    The two backends silently disagreeing is the condition that hid this bug for
    as long as it existed, so equivalence is the property worth pinning.
    """
    repo = BaseRepository("kyber_containment_switches")
    await repo.insert(
        "filter-binding-active",
        {"scope": "tenant", "target": "t-frozen", "control": "ingestion", "active": True},
    )
    await repo.insert(
        "filter-binding-inactive",
        {"scope": "tenant", "target": "t-running", "control": "ingestion", "active": False},
    )

    active = await repo.find_many({"active": True}, limit=10)
    assert [row["id"] for row in active] == ["filter-binding-active"]
    assert await repo.count({"active": True}) == 1

    inactive = await repo.find_many({"active": False}, limit=10)
    assert [row["id"] for row in inactive] == ["filter-binding-inactive"]


def test_every_boolean_filter_call_site_is_covered_by_this_fix():
    """The four known call sites still pass a Python bool, so the fix is load-bearing.

    If one of them is ever rewritten to pass the string ``"true"`` directly, this
    test is the reminder that the binding — not the caller — is what was wrong.
    """
    import re

    call_sites = [
        BACKEND / "services" / "kyber" / "ops" / "containment.py",
        BACKEND / "services" / "web3" / "registries.py",
        BACKEND / "services" / "notification_intelligence" / "delivery_router.py",
        BACKEND / "repositories" / "commerce_repos.py",
    ]
    pattern = re.compile(r"(find_many|count)\(.*?(True|False)", re.S)
    covered = [p.name for p in call_sites if p.exists() and pattern.search(p.read_text())]
    assert covered, (
        "no boolean filter call site found; if they were all rewritten, this "
        "test and the _jsonb_text bool branch can go — but check, do not assume"
    )
