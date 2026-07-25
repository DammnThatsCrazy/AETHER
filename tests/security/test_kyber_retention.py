"""Short-lived retention class is honored by the storage lifecycle.

Regression guard for a defect where ``StorageLifecycle._retention_days``
recognised only ``legal`` and let everything else fall through to the standard
(default 365 day) window. Five resource types declare
``retention_class: short_lived`` in config/storage_policies.yaml, four of them
security-sensitive Kyber tables — expired workforce sessions, step-up
elevations, and SINGLE-USE WebAuthn / device-proof challenges. Under the
defect those rows were retained for a year.

Everything here is deterministic: the retention windows are injected through
the constructor (no env mutation, so parallel suites are unaffected) and every
sweep is given an explicit ``now=`` (no sleeping).
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from shared.common.common import utc_now  # noqa: E402
from shared.storage.lifecycle import StorageLifecycle  # noqa: E402
from shared.storage.manager import StorageManager  # noqa: E402

# Resource types drawn from config/storage_policies.yaml.
SHORT_LIVED_TYPE = "kyber_workforce_sessions"
SHORT_LIVED_TYPES = (
    "kyber_workforce_sessions",
    "kyber_step_up_grants",
    "kyber_webauthn_challenges",
    "kyber_device_proof_challenges",
    "webhook_quarantine",
)
STANDARD_TYPE = "dune_bronze_records"
LEGAL_TYPE = "consent_receipts"

TENANT = "tenant_alpha"
SHORT_DAYS = 7
STANDARD_DAYS = 365


class FakeDescriptorRepo:
    """In-memory descriptor index supporting the paged scan + mutations."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def seed(self, descriptor_id: str, resource_type: str, created_at: str) -> None:
        self.rows[descriptor_id] = {
            "descriptor_id": descriptor_id,
            "resource_type": resource_type,
            "tenant_id": TENANT,
            "locator": f"obj/{descriptor_id}",
            "created_at": created_at,
        }

    async def find_many(
        self,
        filters: Optional[dict] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        matched = [
            dict(row)
            for row in self.rows.values()
            if all(row.get(k) == v for k, v in (filters or {}).items())
        ]
        return matched[offset : offset + limit]

    async def delete(self, descriptor_id: str) -> None:
        self.rows.pop(descriptor_id, None)

    async def update(self, descriptor_id: str, row: dict) -> None:
        self.rows[descriptor_id] = dict(row)


class FakeHoldRepo:
    """No legal holds — holds are covered by the lifecycle's own suite."""

    async def find_many(self, **_: Any) -> list[dict]:
        return []


class FakeObjectStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, locator: str) -> None:
        self.deleted.append(locator)


class UnusedRowStore:
    """Bronze row store is never reached for these non-Bronze resource types."""

    def __getattr__(self, name: str) -> Any:  # pragma: no cover - guard only
        raise AssertionError(f"row store should not be used (called {name!r})")


def _build(
    *,
    short_days: Optional[int] = SHORT_DAYS,
    standard_days: Optional[int] = STANDARD_DAYS,
) -> tuple[StorageLifecycle, FakeDescriptorRepo, FakeObjectStore]:
    descriptor_repo = FakeDescriptorRepo()
    object_store = FakeObjectStore()
    manager = StorageManager(
        object_store=object_store,
        descriptor_repo=descriptor_repo,
        externalization_enabled=True,
    )
    lifecycle = StorageLifecycle(
        manager=manager,
        row_store=UnusedRowStore(),
        hold_repo=FakeHoldRepo(),
        standard_retention_days=standard_days,
        short_lived_retention_days=short_days,
    )
    return lifecycle, descriptor_repo, object_store


def _seed_aged(repo: FakeDescriptorRepo, resource_type: str, age_days: int) -> str:
    """Seed one descriptor whose object is ``age_days`` old, return its id."""
    descriptor_id = f"desc_{resource_type}_{age_days}"
    created_at = (utc_now() - timedelta(days=age_days)).isoformat()
    repo.seed(descriptor_id, resource_type, created_at)
    return descriptor_id


# ---------------------------------------------------------------------------
# Window resolution
# ---------------------------------------------------------------------------


def test_short_lived_window_is_distinct_from_standard() -> None:
    lifecycle, _, _ = _build()
    short = lifecycle._retention_days(lifecycle.manager.policy_for(SHORT_LIVED_TYPE))
    standard = lifecycle._retention_days(lifecycle.manager.policy_for(STANDARD_TYPE))
    assert short == SHORT_DAYS
    assert standard == STANDARD_DAYS
    assert short < standard


def test_every_short_lived_policy_type_resolves_to_the_short_window() -> None:
    lifecycle, _, _ = _build()
    for resource_type in SHORT_LIVED_TYPES:
        policy = lifecycle.manager.policy_for(resource_type)
        assert policy.retention_class == "short_lived", resource_type
        assert lifecycle._retention_days(policy) == SHORT_DAYS, resource_type


def test_legal_class_resolves_to_no_window() -> None:
    lifecycle, _, _ = _build()
    policy = lifecycle.manager.policy_for(LEGAL_TYPE)
    assert policy.retention_class == "legal"
    assert lifecycle._retention_days(policy) is None


def test_short_lived_window_falls_back_to_settings_default() -> None:
    """Unset constructor override reads settings, and 7 < the standard 365."""
    from config.settings import settings

    lifecycle, _, _ = _build(short_days=None, standard_days=None)
    assert settings.storage_plane.retention_short_lived_days == 7
    assert (
        settings.storage_plane.retention_short_lived_days
        < settings.storage_plane.retention_standard_days
    )
    assert lifecycle._retention_days(
        lifecycle.manager.policy_for(SHORT_LIVED_TYPE)
    ) == settings.storage_plane.retention_short_lived_days


# ---------------------------------------------------------------------------
# Sweep behavior
# ---------------------------------------------------------------------------


async def test_short_lived_type_is_swept_on_the_short_clock() -> None:
    lifecycle, repo, store = _build()
    descriptor_id = _seed_aged(repo, SHORT_LIVED_TYPE, age_days=SHORT_DAYS + 3)

    report = await lifecycle.apply_retention(SHORT_LIVED_TYPE, now=utc_now())

    assert report["skipped"] is None
    assert report["objects_deleted"] == 1
    assert descriptor_id not in repo.rows
    assert store.deleted == [f"obj/{descriptor_id}"]


async def test_short_lived_type_is_not_swept_before_the_short_window() -> None:
    lifecycle, repo, store = _build()
    descriptor_id = _seed_aged(repo, SHORT_LIVED_TYPE, age_days=SHORT_DAYS - 3)

    report = await lifecycle.apply_retention(SHORT_LIVED_TYPE, now=utc_now())

    assert report["objects_deleted"] == 0
    assert descriptor_id in repo.rows
    assert store.deleted == []


async def test_short_lived_type_does_not_use_the_standard_window() -> None:
    """The defect: a 30-day-old session survived because 30 < 365."""
    lifecycle, repo, _ = _build()
    age = 30
    assert SHORT_DAYS < age < STANDARD_DAYS  # only the short clock can expire it
    _seed_aged(repo, SHORT_LIVED_TYPE, age_days=age)

    report = await lifecycle.apply_retention(SHORT_LIVED_TYPE, now=utc_now())

    assert report["objects_deleted"] == 1
    assert repo.rows == {}


async def test_standard_type_still_uses_the_standard_window() -> None:
    lifecycle, repo, _ = _build()
    young = _seed_aged(repo, STANDARD_TYPE, age_days=30)

    report = await lifecycle.apply_retention(STANDARD_TYPE, now=utc_now())
    assert report["objects_deleted"] == 0
    assert young in repo.rows

    report = await lifecycle.apply_retention(
        STANDARD_TYPE, now=utc_now() + timedelta(days=STANDARD_DAYS)
    )
    assert report["objects_deleted"] == 1
    assert young not in repo.rows


@pytest.mark.parametrize("age_days", [1, 400, 10_000])
async def test_legal_type_is_never_swept_regardless_of_age(age_days: int) -> None:
    lifecycle, repo, store = _build()
    descriptor_id = _seed_aged(repo, LEGAL_TYPE, age_days=age_days)

    report = await lifecycle.apply_retention(LEGAL_TYPE, now=utc_now())

    assert report["skipped"] == "retention_class=legal is compliance-owned"
    assert report["objects_deleted"] == 0
    assert descriptor_id in repo.rows
    assert store.deleted == []


@pytest.mark.parametrize("window", [1, 14])
async def test_short_lived_window_is_configurable(window: int) -> None:
    lifecycle, repo, _ = _build(short_days=window)
    kept = _seed_aged(repo, SHORT_LIVED_TYPE, age_days=max(window - 1, 0))
    expired = _seed_aged(repo, SHORT_LIVED_TYPE, age_days=window + 1)

    report = await lifecycle.apply_retention(SHORT_LIVED_TYPE, now=utc_now())

    assert report["objects_deleted"] == 1
    assert expired not in repo.rows
    assert kept in repo.rows


async def test_unknown_resource_type_still_fails_closed() -> None:
    lifecycle, _, _ = _build()
    with pytest.raises(Exception):
        await lifecycle.apply_retention("not_a_real_resource_type", now=utc_now())
