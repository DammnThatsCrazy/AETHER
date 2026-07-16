"""Object-backed Bronze + cross-store lifecycle (PR 8 / FT-8-OBJECT-BACKED-BRONZE).

Exercises ``shared/storage/compaction.py`` + ``shared/storage/lifecycle.py``
under AETHER_ENV=local (in-memory backends, no asyncpg / S3 / zstd required):

  * compaction packs cold Bronze payloads into per-tenant objects, records a
    descriptor, and KEEPS every hot searchable metadata column
  * compaction is flag-gated (default OFF = no-op) and honors the age threshold
  * historical routing: hot rows read hot, externalized rows hydrate through
    the descriptor with sha256 verification; tampered objects are rejected
  * the reconciler stays clean after compaction (no orphans / missing / drift)
  * policy-driven retention (config/storage_policies.yaml retention_class)
    ages out externalized objects AND rows; hard_delete vs tombstone semantics
    across row store + object store + descriptor index; legal class never swept
  * DSR erasure propagates across all three stores — subject rows removed,
    packed objects re-packed WITHOUT the subject (survivors re-pointed), or
    deleted outright when nothing else remains
  * legal holds block retention and DSR deletion until released; unsupported /
    unknown types fail closed
  * the bronze_object_compaction WorkerSpec is registered, flag-gated, and
    owned by the materializer runtime role; the retention worker's storage
    lifecycle pass is gated on STORAGE_LIFECYCLE_RETENTION_ENABLED

Robust to suite ordering: backend modules are evicted and re-imported per
test so one consistent generation of config.settings / repositories.repos /
shared.storage is used. Where exceptions may cross module generations we
assert by exception TYPE NAME rather than class identity.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_BACKEND_PREFIXES = (
    "config", "services", "shared", "middleware", "dependencies", "repositories",
)


def _evict_backend() -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _BACKEND_PREFIXES:
            sys.modules.pop(name, None)


class _Backend:
    """Freshly-imported, mutually-consistent backend module handle."""

    def __init__(self, **storage_plane_overrides):
        _evict_backend()
        self.settings_mod = importlib.import_module("config.settings")
        self.repos = importlib.import_module("repositories.repos")
        self.repos.reset_in_memory_stores()
        self.bulk = importlib.import_module("services.ingestion.bronze_bulk")
        self.object_store_mod = importlib.import_module("shared.storage.object_store")
        self.manager_mod = importlib.import_module("shared.storage.manager")
        self.compaction_mod = importlib.import_module("shared.storage.compaction")
        self.lifecycle_mod = importlib.import_module("shared.storage.lifecycle")
        self.reconciler_mod = importlib.import_module("shared.storage.reconciler")
        self.settings = self.settings_mod.settings
        if storage_plane_overrides:
            object.__setattr__(
                self.settings,
                "storage_plane",
                dataclasses.replace(
                    self.settings.storage_plane, **storage_plane_overrides
                ),
            )
        self.store = self.object_store_mod.InMemoryObjectStore()
        self.descriptor_repo = self.repos.StorageDescriptorRepository()
        self.hold_repo = self.repos.StorageLegalHoldRepository()

    def manager(self, policies_path=None, externalization_enabled=True):
        return self.manager_mod.StorageManager(
            object_store=self.store,
            descriptor_repo=self.descriptor_repo,
            policies_path=policies_path,
            externalization_enabled=externalization_enabled,
        )

    def compactor(self, *, enabled=True, min_age_hours=72, manager=None, **kwargs):
        return self.compaction_mod.BronzeObjectCompactor(
            manager or self.manager(),
            enabled=enabled,
            min_age_hours=min_age_hours,
            **kwargs,
        )

    def lifecycle(self, *, policies_path=None, standard_days=365):
        return self.lifecycle_mod.StorageLifecycle(
            self.manager(policies_path=policies_path),
            hold_repo=self.hold_repo,
            standard_retention_days=standard_days,
        )

    @property
    def bronze_store(self) -> dict:
        return self.repos._IN_MEMORY_STORES.setdefault("bronze_sdk_events", {})

    @property
    def descriptor_store(self) -> dict:
        return self.repos._IN_MEMORY_STORES.setdefault("storage_descriptors", {})


@contextmanager
def fresh(**storage_plane_overrides):
    b = _Backend(**storage_plane_overrides)
    try:
        yield b
    finally:
        _evict_backend()


def _run(coro):
    return asyncio.run(coro)


def _seed(b, *, tenant="t1", n=3, user_id=None, anonymous_id="anon-1",
          age_hours=100, prefix="e") -> None:
    """Seed typed Bronze rows through the real V2 transactional path."""
    stamp = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    events = [
        b.bulk.BronzeSDKEvent(
            tenant_id=tenant,
            event_id=f"{prefix}{i}",
            schema_version="2.0",
            batch_id="batch-1",
            event_type="track",
            event_family="behavioral",
            event_timestamp=stamp,
            received_at=stamp,
            session_id="s1",
            anonymous_id=anonymous_id,
            user_id=user_id,
            entity_id="",
            payload={"k": i, "who": anonymous_id, "nested": {"n": i}},
        )
        for i in range(n)
    ]
    result = _run(b.bulk.ingest_many(events, []))
    assert result.accepted_count == n


def _write_policy_fixture(tmp_path: Path, *, retention_class="standard",
                          delete_behavior="hard_delete",
                          legal_hold_supported=True) -> Path:
    """A minimal registry variant so tombstone/legal semantics are testable
    (StorageManager/StorageLifecycle accept ``policies_path`` for exactly
    this); the REAL registry stays the only production policy source."""
    path = tmp_path / f"policies_{retention_class}_{delete_behavior}.yaml"
    path.write_text(
        "schema_version: 1\n"
        "enforcement_status: enforced\n"
        "policies:\n"
        "  - resource_type: bronze_sdk_events\n"
        "    authoritative_store: postgres\n"
        "    metadata_store: postgres\n"
        "    projection_stores: []\n"
        "    codec: none\n"
        "    format: jsonl\n"
        "    cache_ttl_seconds: 0\n"
        "    materialization_mode: on_demand\n"
        f"    retention_class: {retention_class}\n"
        f"    delete_behavior: {delete_behavior}\n"
        f"    legal_hold_supported: {'true' if legal_hold_supported else 'false'}\n"
        "    allow_adaptive_materialization: false\n"
        "    allow_object_externalization: true\n"
        "    allow_historical_table_storage: true\n"
        "    requires_consent_invalidation: true\n"
        "    requires_permission_hash: false\n"
    )
    return path


# ═══════════════════════════════════════════════════════════════════════════
# COMPACTION — pack → descriptor → hot metadata kept
# ═══════════════════════════════════════════════════════════════════════════

def test_compaction_packs_and_keeps_hot_metadata():
    with fresh() as b:
        _seed(b, n=4)
        stats = _run(b.compactor().compact_once())
        assert stats.enabled is True
        assert stats.candidates == 4
        assert stats.rows_externalized == 4
        assert stats.objects_written == 1  # one tenant → one packed object

        # Descriptor indexed with verified metadata; object bytes durable.
        [descriptor_row] = list(b.descriptor_store.values())
        assert descriptor_row["resource_type"] == "bronze_sdk_events"
        assert descriptor_row["tenant_id"] == "t1"
        assert descriptor_row["record_count"] == 4
        assert b.store.head(descriptor_row["locator"]) is not None

        # Hot searchable metadata is NEVER deleted; only the payload moved.
        assert len(b.bronze_store) == 4
        for row in b.bronze_store.values():
            assert row["payload"] == {}
            assert row["payload_externalized"] is True
            assert row["payload_descriptor_id"] == descriptor_row["descriptor_id"]
            assert row["payload_locator"] == descriptor_row["locator"]
            for kept in ("event_id", "event_type", "event_family", "tenant_id",
                         "anonymous_id", "session_id", "payload_hash",
                         "received_at", "event_timestamp"):
                assert row.get(kept) not in (None, {},), kept
            assert row["anonymous_id"] == "anon-1"


def test_compaction_packs_per_tenant():
    with fresh() as b:
        _seed(b, tenant="t1", n=2, prefix="a")
        _seed(b, tenant="t2", n=3, prefix="z")
        stats = _run(b.compactor().compact_once())
        assert stats.objects_written == 2
        assert stats.rows_externalized == 5
        tenants = {d["tenant_id"]: d["record_count"] for d in b.descriptor_store.values()}
        assert tenants == {"t1": 2, "t2": 3}


def test_compaction_flag_off_is_noop():
    # enabled=None → the compactor reads settings.storage_plane, which
    # defaults OFF in local: nothing is packed, nothing is written.
    with fresh() as b:
        assert b.settings.storage_plane.bronze_compaction_enabled is False
        _seed(b, n=3)
        before = {k: dict(v) for k, v in b.bronze_store.items()}
        stats = _run(b.compactor(enabled=None).compact_once())
        assert stats.enabled is False
        assert stats.rows_externalized == 0
        assert b.bronze_store == before          # rows untouched, payloads hot
        assert b.descriptor_store == {}          # no descriptors
        assert b.store.list() == []              # no objects


def test_compaction_flags_on_via_settings():
    with fresh(bronze_compaction_enabled=True, externalization_enabled=True) as b:
        _seed(b, n=2)
        stats = _run(b.compactor(enabled=None).compact_once())
        assert stats.enabled is True and stats.rows_externalized == 2


def test_compaction_requires_master_externalization_flag():
    # Compaction flag on, master externalization flag off → no-op.
    with fresh(bronze_compaction_enabled=True, externalization_enabled=False) as b:
        _seed(b, n=2)
        stats = _run(b.compactor(enabled=None).compact_once())
        assert stats.enabled is False and b.store.list() == []


def test_compaction_respects_min_age_threshold():
    with fresh() as b:
        _seed(b, n=2, age_hours=1, prefix="hot")    # too fresh to pack
        _seed(b, n=3, age_hours=100, prefix="cold")
        stats = _run(b.compactor(min_age_hours=72).compact_once())
        assert stats.candidates == 3
        assert stats.rows_externalized == 3
        hot = [r for r in b.bronze_store.values() if not r.get("payload_externalized")]
        assert len(hot) == 2 and all(r["payload"] != {} for r in hot)


# ═══════════════════════════════════════════════════════════════════════════
# HISTORICAL ROUTING — hydrate on demand with checksum verification
# ═══════════════════════════════════════════════════════════════════════════

def test_historical_routing_round_trip():
    with fresh() as b:
        _seed(b, n=3, age_hours=100, prefix="cold")
        _seed(b, n=1, age_hours=1, prefix="hot")
        compactor = b.compactor()
        _run(compactor.compact_once())

        for row in b.bronze_store.values():
            payload = _run(compactor.read_payload(row))
            i = int(row["event_id"].removeprefix("cold").removeprefix("hot"))
            assert payload == {"k": i, "who": "anon-1", "nested": {"n": i}}

        # The hot row really routed hot (its payload never left Postgres).
        hot_row = next(
            r for r in b.bronze_store.values() if not r.get("payload_externalized")
        )
        assert hot_row["payload"] != {}


def test_historical_routing_checksum_mismatch_rejected():
    with fresh() as b:
        _seed(b, n=2)
        compactor = b.compactor()
        _run(compactor.compact_once())
        [descriptor_row] = list(b.descriptor_store.values())
        b.store.put(descriptor_row["locator"], b"tampered bytes")
        row = next(iter(b.bronze_store.values()))
        with pytest.raises(Exception) as excinfo:
            _run(compactor.read_payload(row))
        assert type(excinfo.value).__name__ == "ChecksumMismatchError"


def test_historical_routing_missing_descriptor_fails_closed():
    with fresh() as b:
        _seed(b, n=1)
        compactor = b.compactor()
        _run(compactor.compact_once())
        row = next(iter(b.bronze_store.values()))
        b.descriptor_store.clear()
        with pytest.raises(KeyError) as excinfo:
            _run(compactor.read_payload(row))
        assert type(excinfo.value).__name__ == "BronzePayloadUnavailableError"


def test_reconciler_clean_after_compaction():
    with fresh() as b:
        _seed(b, tenant="t1", n=3, prefix="a")
        _seed(b, tenant="t2", n=2, prefix="z")
        _run(b.compactor().compact_once())
        report = _run(
            b.reconciler_mod.reconcile_object_store(
                descriptor_repo=b.descriptor_repo, object_store=b.store,
            )
        )
        assert report.is_clean is True
        assert report.healthy == 2  # one healthy object per tenant


# ═══════════════════════════════════════════════════════════════════════════
# RETENTION — policy retention_class over objects AND rows
# ═══════════════════════════════════════════════════════════════════════════

def test_retention_hard_delete_applies_to_objects_rows_and_descriptors():
    with fresh() as b:
        _seed(b, n=3, prefix="cold")
        _run(b.compactor().compact_once())
        _seed(b, n=2, prefix="hot", age_hours=100)  # expired but never packed
        lifecycle = b.lifecycle(standard_days=365)

        # Not expired yet → nothing removed.
        report = _run(lifecycle.apply_retention("bronze_sdk_events"))
        assert report["objects_deleted"] == 0 and report["rows_deleted"] == 0

        # One year later everything (real policy: hard_delete) ages out.
        future = datetime.now(timezone.utc) + timedelta(days=400)
        report = _run(lifecycle.apply_retention("bronze_sdk_events", now=future))
        assert report["delete_behavior"] == "hard_delete"
        assert report["objects_deleted"] == 1
        assert report["rows_deleted"] == 5     # 3 externalized + 2 hot rows
        assert b.bronze_store == {}
        assert b.descriptor_store == {}
        assert b.store.list() == []
        clean = _run(
            b.reconciler_mod.reconcile_object_store(
                descriptor_repo=b.descriptor_repo, object_store=b.store,
            )
        )
        assert clean.is_clean is True


def test_retention_tombstone_semantics(tmp_path):
    policies = _write_policy_fixture(tmp_path, delete_behavior="tombstone")
    with fresh() as b:
        _seed(b, n=2)
        _run(b.compactor(manager=b.manager(policies_path=policies)).compact_once())
        lifecycle = b.lifecycle(policies_path=policies)
        future = datetime.now(timezone.utc) + timedelta(days=400)
        report = _run(lifecycle.apply_retention("bronze_sdk_events", now=future))
        assert report["objects_tombstoned"] == 1
        assert report["rows_tombstoned"] == 2

        # Object bytes are gone; structural stubs remain in BOTH indexes.
        assert b.store.list() == []
        [descriptor_row] = list(b.descriptor_store.values())
        assert descriptor_row["tombstoned"] is True and descriptor_row["tombstoned_at"]
        assert len(b.bronze_store) == 2
        for row in b.bronze_store.values():
            assert row["tombstoned"] is True
            assert row["payload"] == {}
            assert row["user_id"] is None
            assert row["anonymous_id"] == "" and row["entity_id"] == ""

        # Tombstoned descriptors no longer claim objects → reconciler clean.
        clean = _run(
            b.reconciler_mod.reconcile_object_store(
                descriptor_repo=b.descriptor_repo, object_store=b.store,
            )
        )
        assert clean.is_clean is True

        # A second pass is idempotent — stubs are not re-swept.
        again = _run(lifecycle.apply_retention("bronze_sdk_events", now=future))
        assert again["objects_tombstoned"] == 0


def test_retention_legal_class_is_never_swept(tmp_path):
    policies = _write_policy_fixture(
        tmp_path, retention_class="legal", delete_behavior="tombstone"
    )
    with fresh() as b:
        _seed(b, n=2)
        _run(b.compactor(manager=b.manager(policies_path=policies)).compact_once())
        lifecycle = b.lifecycle(policies_path=policies)
        future = datetime.now(timezone.utc) + timedelta(days=5000)
        report = _run(lifecycle.apply_retention("bronze_sdk_events", now=future))
        assert report["skipped"] == "retention_class=legal is compliance-owned"
        assert len(b.store.list()) == 1 and len(b.descriptor_store) == 1


def test_retention_blocked_by_legal_hold_until_released():
    with fresh() as b:
        _seed(b, n=3)
        _run(b.compactor().compact_once())
        lifecycle = b.lifecycle()
        hold = _run(
            lifecycle.place_hold(
                "t1", reason="litigation L-42", resource_type="bronze_sdk_events",
            )
        )
        future = datetime.now(timezone.utc) + timedelta(days=400)
        report = _run(lifecycle.apply_retention("bronze_sdk_events", now=future))
        assert report["held"] >= 1
        assert report["objects_deleted"] == 0
        assert len(b.store.list()) == 1 and len(b.bronze_store) == 3  # intact

        _run(lifecycle.release_hold(hold["hold_id"], released_by="counsel"))
        report = _run(lifecycle.apply_retention("bronze_sdk_events", now=future))
        assert report["objects_deleted"] == 1
        assert b.store.list() == [] and b.bronze_store == {}


# ═══════════════════════════════════════════════════════════════════════════
# DSR — subject erasure across row store + object store + descriptor index
# ═══════════════════════════════════════════════════════════════════════════

def test_dsr_erasure_repacks_objects_without_subject():
    with fresh() as b:
        _seed(b, n=2, anonymous_id="anon-a", user_id="user-a", prefix="a")
        _seed(b, n=3, anonymous_id="anon-b", prefix="z")
        compactor = b.compactor()
        _run(compactor.compact_once())
        [old_descriptor] = list(b.descriptor_store.values())

        lifecycle = b.lifecycle()
        report = _run(lifecycle.dsr_erase_subject("t1", "anon-a"))
        assert report["status"] == "completed"
        assert report["rows_removed"] == 2
        assert report["packed_records_removed"] == 2
        assert report["objects_repacked"] == 1

        # Row store: subject rows gone, survivors intact.
        assert len(b.bronze_store) == 3
        assert all(r["anonymous_id"] == "anon-b" for r in b.bronze_store.values())

        # Descriptor index: old descriptor replaced by the re-packed one.
        assert old_descriptor["descriptor_id"] not in b.descriptor_store
        [new_descriptor] = list(b.descriptor_store.values())
        assert new_descriptor["record_count"] == 3
        assert new_descriptor["lineage"] == [old_descriptor["descriptor_id"]]

        # Object store: exactly the re-packed object; no subject data inside.
        assert b.store.list() == [new_descriptor["locator"]]
        records = _run(b.manager().hydrate(
            b.compaction_mod.StorageDescriptor.from_dict(new_descriptor)
        ))
        assert len(records) == 3
        assert all(r["anonymous_id"] == "anon-b" for r in records)

        # Survivors were re-pointed and still hydrate through routing.
        survivor = next(iter(b.bronze_store.values()))
        assert survivor["payload_descriptor_id"] == new_descriptor["descriptor_id"]
        payload = _run(compactor.read_payload(survivor))
        assert payload["who"] == "anon-b"

        clean = _run(
            b.reconciler_mod.reconcile_object_store(
                descriptor_repo=b.descriptor_repo, object_store=b.store,
            )
        )
        assert clean.is_clean is True


def test_dsr_erasure_deletes_object_when_subject_owned_all_records():
    with fresh() as b:
        _seed(b, n=2, anonymous_id="anon-a", user_id="user-a")
        _run(b.compactor().compact_once())
        report = _run(b.lifecycle().dsr_erase_subject("t1", "user-a"))
        assert report["status"] == "completed"
        assert report["objects_deleted"] == 1
        assert report["objects_repacked"] == 0
        assert b.bronze_store == {} and b.descriptor_store == {} and b.store.list() == []


def test_dsr_erasure_covers_hot_unpacked_rows_too():
    with fresh() as b:
        _seed(b, n=2, anonymous_id="anon-a", age_hours=1)  # never compacted
        report = _run(b.lifecycle().dsr_erase_subject("t1", "anon-a"))
        assert report["rows_removed"] == 2
        assert b.bronze_store == {}


def test_dsr_blocked_by_legal_hold_and_release_unblocks():
    with fresh() as b:
        _seed(b, n=2, anonymous_id="anon-a", prefix="a")
        _seed(b, n=1, anonymous_id="anon-b", prefix="z")
        _run(b.compactor().compact_once())
        lifecycle = b.lifecycle()
        hold = _run(
            lifecycle.place_hold(
                "t1", reason="regulatory inquiry", subject_ref="anon-a",
            )
        )

        # Subject under hold → blocked, NOTHING mutated.
        blocked = _run(lifecycle.dsr_erase_subject("t1", "anon-a"))
        assert blocked["status"] == "blocked_legal_hold"
        assert blocked["hold_id"] == hold["hold_id"]
        assert blocked["rows_removed"] == 0
        assert len(b.bronze_store) == 3 and len(b.store.list()) == 1

        # A hold scoped to anon-a does not block another subject's DSR.
        other = _run(lifecycle.dsr_erase_subject("t1", "anon-b"))
        assert other["status"] == "completed" and other["rows_removed"] == 1

        _run(lifecycle.release_hold(hold["hold_id"]))
        unblocked = _run(lifecycle.dsr_erase_subject("t1", "anon-a"))
        assert unblocked["status"] == "completed"
        assert unblocked["rows_removed"] == 2


def test_deletion_plan_reaches_externalized_objects_via_adapter():
    with fresh() as b:
        _seed(b, n=2, anonymous_id="anon-a", user_id="user-a", prefix="a")
        _seed(b, n=1, anonymous_id="anon-b", prefix="z")
        _run(b.compactor().compact_once())

        privacy = importlib.import_module("shared.privacy.retention")
        plan = privacy.DeletionPlan("user-a", "t1")
        plan.build_standard_plan()
        step = next(
            s for s in plan.steps
            if s["store"] == "object_store" and s["table"] == "bronze_sdk_events"
        )
        assert step["behavior"] == "hard_delete"

        adapter = b.lifecycle_mod.ExternalizedBronzeDSRAdapter(
            "t1", lifecycle=b.lifecycle()
        )
        result = _run(
            plan.execute({"object_store:bronze_sdk_events": adapter})
        )
        executed = next(
            s for s in result["steps"]
            if s["store"] == "object_store" and s["table"] == "bronze_sdk_events"
        )
        assert executed["status"] == "executed"
        assert executed["records_affected"] == 4  # 2 rows + 2 packed records
        assert all(r["anonymous_id"] == "anon-b" for r in b.bronze_store.values())


# ═══════════════════════════════════════════════════════════════════════════
# LEGAL HOLDS — fail-closed placement
# ═══════════════════════════════════════════════════════════════════════════

def test_place_hold_fails_closed():
    with fresh() as b:
        lifecycle = b.lifecycle()
        with pytest.raises(ValueError):
            _run(lifecycle.place_hold("", reason="x"))
        with pytest.raises(ValueError):
            _run(lifecycle.place_hold("t1", reason="   "))
        with pytest.raises(KeyError) as excinfo:
            _run(lifecycle.place_hold(
                "t1", reason="x", resource_type="no_such_persistent_type",
            ))
        assert type(excinfo.value).__name__ == "UnknownResourceTypeError"


def test_place_hold_rejected_when_policy_forbids_holds(tmp_path):
    policies = _write_policy_fixture(tmp_path, legal_hold_supported=False)
    with fresh() as b:
        lifecycle = b.lifecycle(policies_path=policies)
        with pytest.raises(Exception) as excinfo:
            _run(lifecycle.place_hold(
                "t1", reason="x", resource_type="bronze_sdk_events",
            ))
        assert type(excinfo.value).__name__ == "StoragePolicyViolationError"


# ═══════════════════════════════════════════════════════════════════════════
# Runtime wiring — WorkerSpec, role ownership, retention-worker flag gate
# ═══════════════════════════════════════════════════════════════════════════

def test_materializer_role_owns_the_bronze_compaction_spec():
    with fresh() as b:
        roles = importlib.import_module("services.runtime.roles")
        assert "bronze_object_compaction" in roles.ROLE_TO_SPEC_NAMES["materializer"]
        picked = roles.specs_for_role(
            "materializer", ["bronze_object_compaction", "job_worker"]
        )
        assert picked == ["bronze_object_compaction"]
        assert roles.specs_for_role("api", ["bronze_object_compaction"]) == []


def test_bronze_compaction_spec_is_registered_and_flag_gated():
    with fresh() as b:
        specs_mod = importlib.import_module("services.runtime.specs")
        specs = specs_mod.build_worker_specs(
            registry=SimpleNamespace(producer=None), settings=b.settings
        )
        spec = next(s for s in specs if s.name == "bronze_object_compaction")
        assert spec.enabled() is False  # every FT-8 flag defaults OFF
        assert spec.required is False

        # Compaction alone is not enough — the master flag must also be on.
        object.__setattr__(
            b.settings, "storage_plane",
            dataclasses.replace(
                b.settings.storage_plane, bronze_compaction_enabled=True
            ),
        )
        assert spec.enabled() is False
        object.__setattr__(
            b.settings, "storage_plane",
            dataclasses.replace(
                b.settings.storage_plane, externalization_enabled=True
            ),
        )
        assert spec.enabled() is True

        # The reconciler flag alone also schedules the worker (FT-7 deferral).
        object.__setattr__(
            b.settings, "storage_plane",
            dataclasses.replace(
                b.settings.storage_plane,
                bronze_compaction_enabled=False,
                externalization_enabled=False,
                reconciler_enabled=True,
            ),
        )
        assert spec.enabled() is True


def test_retention_worker_storage_lifecycle_pass_is_flag_gated():
    with fresh() as b:
        worker = importlib.import_module("services.security.retention_worker")
        # Default OFF → pure no-op (None), FT-7-era behavior unchanged.
        assert _run(worker.storage_lifecycle_retention_pass()) is None

        object.__setattr__(
            b.settings, "storage_plane",
            dataclasses.replace(
                b.settings.storage_plane, lifecycle_retention_enabled=True
            ),
        )
        report = _run(worker.storage_lifecycle_retention_pass())
        assert isinstance(report, dict)
        assert "bronze_sdk_events" in report


def test_pg_shaped_string_payloads_are_decoded_for_packing_and_routing():
    """asyncpg returns jsonb columns as JSON strings (the pool registers no
    codec). Packing and hot-path routing must decode string payloads instead
    of crashing in dict() — regression for the PG-only compaction path."""
    with fresh() as b:
        pg_shaped_row = {
            "id": "row-1",
            "event_id": "e1",
            "user_id": "u1",
            "anonymous_id": "",
            "entity_id": "u1",
            "payload": '{"k": "v", "n": 1}',  # str, as asyncpg returns jsonb
            "payload_externalized": False,
        }
        packed = b.compaction_mod.BronzeObjectCompactor._packed_record(pg_shaped_row)
        assert packed["payload"] == {"k": "v", "n": 1}

        compactor = b.compactor()
        assert _run(compactor.read_payload(pg_shaped_row)) == {"k": "v", "n": 1}

        # Dict payloads (in-memory backend shape) keep working identically.
        dict_row = dict(pg_shaped_row, payload={"k": "v", "n": 1})
        assert b.compaction_mod.BronzeObjectCompactor._packed_record(dict_row)[
            "payload"
        ] == {"k": "v", "n": 1}
        assert _run(compactor.read_payload(dict_row)) == {"k": "v", "n": 1}


# ═══════════════════════════════════════════════════════════════════════════
# REVIEW FINDINGS (PR #450) — pagination, row-age retention, races, DSAR wiring
# ═══════════════════════════════════════════════════════════════════════════

def test_active_hold_pages_past_the_first_repository_page():
    """A matching hold beyond the first page must still block deletion."""
    with fresh() as b:
        b.lifecycle_mod._HOLD_PAGE_SIZE = 2  # exercise pagination itself
        lc = b.lifecycle()
        # Five active holds; only the LAST one covers bronze_sdk_events.
        for i in range(4):
            _run(lc.place_hold("t1", reason=f"other-{i}", resource_type="consent_records"))
        _run(lc.place_hold("t1", reason="the-real-block", resource_type="bronze_sdk_events"))

        hold = _run(lc.active_hold("t1", "bronze_sdk_events"))
        assert hold is not None and hold["reason"] == "the-real-block"


def test_retention_ages_externalized_bronze_from_source_row_age():
    """Compaction must not grant packed payloads a fresh retention window:
    rows received 400 days ago and compacted TODAY are already expired."""
    with fresh() as b:
        _seed(b, n=3, age_hours=400 * 24)  # received 400 days ago
        compactor = b.compactor(min_age_hours=1)
        stats = _run(compactor.compact_once())
        assert stats.rows_externalized == 3  # descriptor created_at = today

        lc = b.lifecycle(standard_days=365)
        report = _run(lc.apply_retention())
        assert report["objects_deleted"] == 1
        assert report["rows_deleted"] == 3
        assert b.store.list() == []
        assert b.bronze_store == {}

        # Inverse: young rows packed under an OLD descriptor are NOT swept —
        # the newest source row governs, in both directions.
        _seed(b, n=2, age_hours=24, prefix="young")
        _run(b.compactor(min_age_hours=0).compact_once())
        [descriptor_row] = b.descriptor_store.values()
        descriptor_row["created_at"] = "2020-01-01T00:00:00+00:00"
        report = _run(lc.apply_retention())
        assert report["objects_deleted"] == 0 and report["rows_deleted"] == 0


def test_retention_and_dsr_paginate_all_descriptors():
    """Expired descriptors (and a subject's packed objects) beyond the first
    repository page must still be visited."""
    with fresh() as b:
        b.lifecycle_mod._DESCRIPTOR_PAGE_SIZE = 2
        # Five tenants, five packed objects — all expired by row age.
        for i in range(5):
            _seed(b, tenant=f"t{i}", n=1, age_hours=400 * 24, prefix=f"t{i}e")
        _run(b.compactor(min_age_hours=1).compact_once())
        assert len(b.descriptor_store) == 5

        lc = b.lifecycle(standard_days=365)
        report = _run(lc.apply_retention())
        assert report["objects_deleted"] == 5
        assert b.descriptor_store == {}


def test_dsr_erasure_pages_subject_rows_and_descriptors():
    """High-volume subjects: every row and every packed object is reached even
    when they span multiple repository pages."""
    with fresh() as b:
        b.lifecycle_mod._DESCRIPTOR_PAGE_SIZE = 2
        b.lifecycle_mod._SUBJECT_ROW_PAGE_SIZE = 2
        # Three separate compactions → three packed objects for the subject...
        for j in range(3):
            _seed(b, n=2, anonymous_id="target", age_hours=100, prefix=f"pack{j}e")
            _run(b.compactor(min_age_hours=1).compact_once())
        # ...plus five hot rows (spanning 3 subject-row pages).
        _seed(b, n=5, anonymous_id="target", age_hours=10, prefix="hot")

        report = _run(b.lifecycle().dsr_erase_subject("t1", "target"))
        assert report["status"] == "completed"
        assert report["rows_removed"] == 11  # 6 externalized-metadata + 5 hot
        assert report["packed_records_removed"] == 6
        assert report["objects_deleted"] == 3
        # Nothing of the subject survives anywhere.
        assert all(
            not any(r.get(f) == "target" for f in b.compaction_mod.SUBJECT_FIELDS)
            for r in b.bronze_store.values()
        )
        assert b.store.list() == []


def test_compaction_race_rebuilds_pack_without_concurrently_erased_rows():
    """Rows deleted or tombstoned between candidate selection and the mark
    must not leave their payloads inside the packed object."""
    with fresh() as b:
        _seed(b, n=3, anonymous_id="racer", age_hours=100)
        compactor = b.compactor(min_age_hours=1)

        original_mark = compactor.rows.mark_externalized

        async def race_then_mark(row_ids, descriptor_id, locator):
            # Concurrent DSR wins the race: one row hard-deleted, one tombstoned.
            await compactor.rows.delete_rows([row_ids[0]])
            await compactor.rows.tombstone_rows([row_ids[1]])
            return await original_mark(row_ids, descriptor_id, locator)

        compactor.rows.mark_externalized = race_then_mark
        stats = _run(compactor.compact_once())
        assert stats.rows_externalized == 1  # only the true survivor

        # Exactly one live descriptor/object, containing ONLY the survivor.
        live = [d for d in b.descriptor_store.values() if not d.get("tombstoned")]
        assert len(live) == 1
        descriptor = b.compaction_mod.StorageDescriptor.from_dict(live[0])
        records = _run(compactor.manager.hydrate(descriptor))
        assert len(records) == 1
        assert all(r.get("anonymous_id") == "racer" for r in records)
        assert len(b.store.list()) == 1  # the stale object was deleted

        # The survivor still routes to its payload through the rebuilt pack.
        survivor_row = next(
            r for r in b.bronze_store.values()
            if r.get("payload_externalized") and not r.get("tombstoned")
        )
        payload = _run(compactor.read_payload(survivor_row))
        assert payload["who"] == "racer"


def test_default_dsar_erasure_reaches_externalized_bronze():
    """DSARRequest.process_erasure with NO adapters must still erase packed
    payloads — the canonical adapter is wired automatically.

    Uses the module's shared in-memory object store (what default resolution
    binds, mirroring production where both paths hit the same S3 bucket) so
    the auto-wired adapter sees the object the compactor wrote.

    Env is pinned for the duration: default object-store resolution reads
    AETHER_ENV / OBJECT_BACKEND at import, and other suites in the same
    worker mutate os.environ directly — without pinning, a leaked non-local
    env sends the adapter down the fail-closed S3 path."""
    import os

    _keys = ("AETHER_ENV", "OBJECT_BACKEND", "DATABASE_URL")
    saved = {k: os.environ.get(k) for k in _keys}
    os.environ["AETHER_ENV"] = "local"
    os.environ["OBJECT_BACKEND"] = "memory"
    os.environ.pop("DATABASE_URL", None)
    try:
        with fresh() as b:
            retention = importlib.import_module("shared.privacy.retention")
            shared_store = b.object_store_mod._SHARED_MEMORY_STORE  # fresh per eviction
            manager = b.manager_mod.StorageManager(
                object_store=shared_store,
                descriptor_repo=b.descriptor_repo,
                externalization_enabled=True,
            )
            _seed(b, n=2, anonymous_id="subject-x", age_hours=100)
            _run(b.compactor(min_age_hours=1, manager=manager).compact_once())
            assert len(shared_store.list()) == 1

            request = retention.DSARRequest(
                request_type="erasure", entity_id="subject-x", tenant_id="t1"
            )
            result = _run(request.process_erasure())
            failed_steps = [
                f"{s['store']}:{s['table']} -> {s.get('error')}"
                for s in result.get("steps", result.get("results", []))
                if isinstance(s, dict) and s.get("status") == "failed"
            ]
            assert result["failed"] == 0, f"failed steps: {failed_steps}"

            # Regardless of report shape: the packed object is actually gone.
            assert shared_store.list() == []
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ═══════════════════════════════════════════════════════════════════════════
# REVIEW FINDINGS, wave 2 — legacy V1 rows, per-descriptor row paging,
# hot-row retention paging, reconciler descriptor paging
# ═══════════════════════════════════════════════════════════════════════════

def test_compaction_never_touches_legacy_v1_bronze_rows():
    """Legacy V1 BaseRepository rows carry the raw event only inside the data
    envelope (typed columns NULL/absent). Compacting them would pack {} and
    then destroy the original payload — they must be excluded entirely."""
    with fresh() as b:
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        legacy_row = {  # BaseRepository shape: NO typed event_id column
            "id": "legacy-1",
            "tenant_id": "t1",
            "source": "sdk",
            "provider_record_id": "evt-legacy",
            "payload": {"raw": "precious-v1-event"},
            "created_at": old,
            "updated_at": old,
        }
        b.bronze_store["legacy-1"] = dict(legacy_row)
        _seed(b, n=1, age_hours=100)  # one typed V2 row alongside

        stats = _run(b.compactor(min_age_hours=1).compact_once())
        assert stats.rows_externalized == 1  # only the typed row

        preserved = b.bronze_store["legacy-1"]
        assert preserved["payload"] == {"raw": "precious-v1-event"}
        assert not preserved.get("payload_externalized")

        # Retention's hot-row path (same candidate query) also skips it.
        report = _run(b.lifecycle(standard_days=365).apply_retention())
        assert "legacy-1" in b.bronze_store


def test_lifecycle_pages_rows_within_one_descriptor():
    """Expiry decisions and descriptor-scope removal must see EVERY row under
    a descriptor, not the first page — otherwise surviving rows are left
    pointing at a deleted descriptor."""
    with fresh() as b:
        _seed(b, n=5, age_hours=400 * 24)
        _run(b.compactor(min_age_hours=1, batch_size=500).compact_once())
        [descriptor_row] = b.descriptor_store.values()
        descriptor_id = descriptor_row["descriptor_id"]

        # Paged fetch equals the full set even with a tiny page size.
        rows = _run(b.compaction_mod.BronzeRowStore().all_rows_for_descriptor(
            descriptor_id, page_size=2
        ))
        assert len(rows) == 5

        report = _run(b.lifecycle(standard_days=365).apply_retention())
        assert report["rows_deleted"] == 5  # no stranded rows
        assert b.bronze_store == {}
        assert b.descriptor_store == {}


def test_retention_hot_row_pass_is_exhaustive():
    """One retention pass removes EVERY expired hot row, not one page."""
    with fresh() as b:
        b.lifecycle_mod._SUBJECT_ROW_PAGE_SIZE = 2
        _seed(b, n=5, age_hours=400 * 24)  # expired, never externalized

        report = _run(b.lifecycle(standard_days=365).apply_retention())
        assert report["rows_deleted"] == 5
        assert b.bronze_store == {}


def test_reconciler_pages_all_descriptors():
    """Descriptors beyond one page must not be misreported as orphans."""
    with fresh() as b:
        for i in range(5):
            _seed(b, tenant=f"t{i}", n=1, age_hours=100, prefix=f"t{i}e")
        _run(b.compactor(min_age_hours=1).compact_once())
        assert len(b.descriptor_store) == 5

        report = _run(b.reconciler_mod.reconcile_object_store(
            descriptor_repo=b.descriptor_repo,
            object_store=b.store,
            limit=2,  # page size far below the descriptor count
            emit_metrics=False,
        ))
        assert report.orphan_objects == [] or report.orphan_objects == ()
        assert report.missing_objects == [] or report.missing_objects == ()
        assert report.is_clean
