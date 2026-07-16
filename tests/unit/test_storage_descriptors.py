"""Storage descriptors + policies + manager + object protocol + reconciler (PR 7).

Exercises the Elastic Data Plane foundation (``shared/storage/``) under
AETHER_ENV=local (in-memory backends, no asyncpg / S3 / zstd required):

  * StorageDescriptor round-trip (to_dict/from_dict), auto id/created_at,
    required-field validation
  * StorageManager policy resolution — known type resolves, unknown type
    FAILS CLOSED with a KeyError subclass
  * externalize/hydrate round trip with checksum verification; the codec
    ACTUALLY applied is recorded on the descriptor (zstd -> gzip fallback
    when the zstd module is absent locally)
  * checksum mismatch on hydrate is rejected
  * policy-forbidden externalization and the master storage-plane flag
  * in-memory object store protocol semantics (put/get/head/delete/list)
  * reconciler detection of missing objects, orphan objects, checksum drift
    (pure core + the IO wrapper over the in-memory store)
  * coverage-gate self-test: every persistent resource type derived from the
    repo (repos.py stores + alembic-created tables) has a policy in
    config/storage_policies.yaml, and the gate's inventory really derives
    from the repo (a new repository without a policy would fail)

Robust to suite ordering: backend modules are evicted and re-imported per
test so one consistent generation of config.settings / repositories.repos /
shared.storage is used. Where exceptions may cross module generations we
assert by exception TYPE NAME rather than class identity.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import importlib.util
import sys
from pathlib import Path

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
        self.descriptor_mod = importlib.import_module("shared.storage.descriptor")
        self.object_store_mod = importlib.import_module("shared.storage.object_store")
        self.manager_mod = importlib.import_module("shared.storage.manager")
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

    def manager(self, **kwargs):
        kwargs.setdefault("object_store", self.object_store_mod.InMemoryObjectStore())
        kwargs.setdefault("descriptor_repo", self.repos.StorageDescriptorRepository())
        kwargs.setdefault("externalization_enabled", True)
        return self.manager_mod.StorageManager(**kwargs)

    @property
    def descriptor_store(self) -> dict:
        return self.repos._IN_MEMORY_STORES.setdefault("storage_descriptors", {})


def _run(coro):
    return asyncio.run(coro)


def _load_gate_module():
    """Load scripts/release/check_storage_policies.py by path (self-test)."""
    spec = importlib.util.spec_from_file_location(
        "check_storage_policies_under_test",
        ROOT / "scripts" / "release" / "check_storage_policies.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _policy_resource_types() -> set[str]:
    import yaml

    data = yaml.safe_load((ROOT / "config" / "storage_policies.yaml").read_text())
    return {p["resource_type"] for p in data["policies"]}


_RECORDS = [{"event_id": f"e{i}", "value": i, "nested": {"n": i}} for i in range(7)]


# ═══════════════════════════════════════════════════════════════════════════
# DESCRIPTOR
# ═══════════════════════════════════════════════════════════════════════════

def test_descriptor_round_trip():
    backend = _Backend()
    StorageDescriptor = backend.descriptor_mod.StorageDescriptor
    descriptor = StorageDescriptor(
        resource_type="bronze_sdk_events",
        tenant_id="t-1",
        locator="bronze_sdk_events/t-1/sd_abc.jsonl.zstd",
        codec="zstd",
        format="jsonl",
        checksum_sha256="a" * 64,
        size_bytes=123,
        record_count=7,
        lineage=["e1", "e2"],
    )
    # lineage normalized to tuple; id + created_at auto-filled
    assert descriptor.lineage == ("e1", "e2")
    assert descriptor.descriptor_id.startswith("sd_")
    assert descriptor.created_at
    rebuilt = StorageDescriptor.from_dict(descriptor.to_dict())
    assert rebuilt == descriptor


def test_descriptor_requires_core_fields():
    backend = _Backend()
    StorageDescriptor = backend.descriptor_mod.StorageDescriptor
    with pytest.raises(ValueError):
        StorageDescriptor(
            resource_type="", tenant_id="t", locator="k", codec="none",
            format="jsonl", checksum_sha256="c" * 64, size_bytes=1, record_count=1,
        )
    with pytest.raises(ValueError):
        StorageDescriptor(
            resource_type="events", tenant_id="t", locator="", codec="none",
            format="jsonl", checksum_sha256="c" * 64, size_bytes=1, record_count=1,
        )
    with pytest.raises(ValueError):
        StorageDescriptor(
            resource_type="events", tenant_id="t", locator="k", codec="none",
            format="jsonl", checksum_sha256="", size_bytes=1, record_count=1,
        )


# ═══════════════════════════════════════════════════════════════════════════
# POLICY RESOLUTION
# ═══════════════════════════════════════════════════════════════════════════

def test_policy_resolution_known_type():
    backend = _Backend()
    manager = backend.manager()
    policy = manager.policy_for("bronze_sdk_events")
    assert policy.resource_type == "bronze_sdk_events"
    assert policy.codec == "zstd"
    assert policy.format == "jsonl"
    assert policy.allow_object_externalization is True
    assert policy.requires_consent_invalidation is True
    legal = manager.policy_for("consent_records")
    assert legal.retention_class == "legal"
    assert legal.delete_behavior == "tombstone"
    assert legal.allow_object_externalization is False


def test_policy_unknown_type_fails_closed():
    backend = _Backend()
    manager = backend.manager()
    with pytest.raises(KeyError) as excinfo:
        manager.policy_for("definitely_not_a_persistent_type")
    # Cross-module-generation safe: assert by type NAME, and that it is a
    # KeyError subclass (fail-closed contract).
    assert type(excinfo.value).__name__ == "UnknownResourceTypeError"
    mro_names = [c.__name__ for c in type(excinfo.value).__mro__]
    assert "KeyError" in mro_names


# ═══════════════════════════════════════════════════════════════════════════
# OBJECT STORE (in-memory implementation of the protocol)
# ═══════════════════════════════════════════════════════════════════════════

def test_in_memory_object_store_protocol():
    backend = _Backend()
    store = backend.object_store_mod.InMemoryObjectStore()

    store.put("a/1", b"one")
    store.put("a/2", b"two-2")
    store.put("b/1", b"three")

    assert store.get("a/1") == b"one"
    stat = store.head("a/2")
    assert stat is not None and stat.size_bytes == 5 and stat.key == "a/2"
    assert store.head("nope") is None
    assert store.list("a/") == ["a/1", "a/2"]
    assert store.list() == ["a/1", "a/2", "b/1"]
    assert store.delete("a/1") is True
    assert store.delete("a/1") is False
    with pytest.raises(KeyError) as excinfo:
        store.get("a/1")
    assert type(excinfo.value).__name__ == "ObjectNotFoundError"


# ═══════════════════════════════════════════════════════════════════════════
# EXTERNALIZE / HYDRATE
# ═══════════════════════════════════════════════════════════════════════════

def test_externalize_hydrate_round_trip_with_checksum():
    backend = _Backend()
    manager = backend.manager()
    descriptor = _run(
        manager.externalize(
            "bronze_sdk_events", "t-1", _RECORDS, lineage=["e0", "e1"],
        )
    )
    # descriptor carries verified metadata
    assert descriptor.resource_type == "bronze_sdk_events"
    assert descriptor.tenant_id == "t-1"
    assert descriptor.record_count == len(_RECORDS)
    assert descriptor.size_bytes > 0
    assert len(descriptor.checksum_sha256) == 64
    assert descriptor.format == "jsonl"
    # codec is whatever was ACTUALLY applied: zstd, or gzip when the zstd
    # module is absent locally (policy requested zstd either way)
    assert descriptor.codec in ("zstd", "gzip")
    assert descriptor.lineage == ("e0", "e1")

    hydrated = _run(manager.hydrate(descriptor))
    assert hydrated == _RECORDS

    # descriptor persisted through the BaseRepository-shaped store
    row = backend.descriptor_store[descriptor.descriptor_id]
    assert row["locator"] == descriptor.locator
    assert row["checksum_sha256"] == descriptor.checksum_sha256
    assert row["tenant_id"] == "t-1"


def test_externalize_policy_forbidden_fails():
    backend = _Backend()
    manager = backend.manager()
    # consent_records policy: allow_object_externalization = false
    with pytest.raises(Exception) as excinfo:
        _run(manager.externalize("consent_records", "t-1", _RECORDS))
    assert type(excinfo.value).__name__ == "StoragePolicyViolationError"


def test_externalize_unknown_type_fails_closed():
    backend = _Backend()
    manager = backend.manager()
    with pytest.raises(KeyError) as excinfo:
        _run(manager.externalize("no_such_type", "t-1", _RECORDS))
    assert type(excinfo.value).__name__ == "UnknownResourceTypeError"


def test_externalize_master_flag_defaults_off_in_local():
    # externalization_enabled=None -> read settings.storage_plane, which
    # defaults OFF in local: externalize refuses even for an allowed type.
    backend = _Backend()
    assert backend.settings.storage_plane.externalization_enabled is False
    assert backend.settings.storage_plane.reconciler_enabled is False
    manager = backend.manager(externalization_enabled=None)
    with pytest.raises(Exception) as excinfo:
        _run(manager.externalize("bronze_sdk_events", "t-1", _RECORDS))
    assert type(excinfo.value).__name__ == "StoragePolicyViolationError"


def test_externalize_master_flag_on_via_settings():
    backend = _Backend(externalization_enabled=True)
    manager = backend.manager(externalization_enabled=None)
    descriptor = _run(manager.externalize("bronze_sdk_events", "t-1", _RECORDS))
    assert descriptor.record_count == len(_RECORDS)


def test_hydrate_checksum_mismatch_rejected():
    backend = _Backend()
    store = backend.object_store_mod.InMemoryObjectStore()
    manager = backend.manager(object_store=store)
    descriptor = _run(manager.externalize("bronze_sdk_events", "t-1", _RECORDS))
    # corrupt the stored object; hydrate must refuse
    store.put(descriptor.locator, b"tampered bytes")
    with pytest.raises(Exception) as excinfo:
        _run(manager.hydrate(descriptor))
    assert type(excinfo.value).__name__ == "ChecksumMismatchError"


# ═══════════════════════════════════════════════════════════════════════════
# RECONCILER
# ═══════════════════════════════════════════════════════════════════════════

def test_reconciler_pure_core_detects_missing_orphan_drift():
    backend = _Backend()
    reconcile = backend.reconciler_mod.reconcile
    sha256_hex = backend.descriptor_mod.sha256_hex

    healthy_bytes = b"healthy"
    drifted_bytes = b"drifted"
    descriptors = [
        {"locator": "k/healthy", "checksum_sha256": sha256_hex(healthy_bytes)},
        {"locator": "k/missing", "checksum_sha256": sha256_hex(b"gone")},
        {"locator": "k/drift", "checksum_sha256": sha256_hex(b"original")},
    ]
    object_checksums = {
        "k/healthy": sha256_hex(healthy_bytes),
        "k/drift": sha256_hex(drifted_bytes),   # bytes changed after write
        "k/orphan": sha256_hex(b"unclaimed"),   # no descriptor claims it
    }
    report = reconcile(descriptors, object_checksums)
    assert report.scanned_descriptors == 3
    assert report.scanned_objects == 3
    assert report.healthy == 1
    assert report.missing_objects == ("k/missing",)
    assert report.orphan_objects == ("k/orphan",)
    assert report.checksum_drift == ("k/drift",)
    assert report.is_clean is False
    as_dict = report.to_dict()
    assert as_dict["missing_objects"] == ["k/missing"]
    assert as_dict["is_clean"] is False


def test_reconciler_clean_report():
    backend = _Backend()
    reconcile = backend.reconciler_mod.reconcile
    sha256_hex = backend.descriptor_mod.sha256_hex
    descriptors = [{"locator": "k/1", "checksum_sha256": sha256_hex(b"x")}]
    report = reconcile(descriptors, {"k/1": sha256_hex(b"x")})
    assert report.is_clean is True
    assert report.healthy == 1


def test_reconcile_object_store_wrapper_end_to_end():
    backend = _Backend()
    store = backend.object_store_mod.InMemoryObjectStore()
    repo = backend.repos.StorageDescriptorRepository()
    manager = backend.manager(object_store=store, descriptor_repo=repo)

    d1 = _run(manager.externalize("bronze_sdk_events", "t-1", _RECORDS[:3]))
    d2 = _run(manager.externalize("dune_bronze_records", "t-1", _RECORDS[3:]))

    # induce all three failure classes
    store.delete(d1.locator)                       # missing object
    store.put(d2.locator, b"corrupted")            # checksum drift
    store.put("orphans/unclaimed.bin", b"???")     # orphan object

    report = _run(
        backend.reconciler_mod.reconcile_object_store(
            descriptor_repo=repo, object_store=store,
        )
    )
    assert report.missing_objects == (d1.locator,)
    assert report.checksum_drift == (d2.locator,)
    assert report.orphan_objects == ("orphans/unclaimed.bin",)
    assert report.is_clean is False


# ═══════════════════════════════════════════════════════════════════════════
# COVERAGE GATE SELF-TEST — CI fails if a persistent type lacks a policy
# ═══════════════════════════════════════════════════════════════════════════

def test_every_persistent_type_has_a_policy():
    gate = _load_gate_module()
    inventory = gate.persistent_resource_inventory(ROOT)
    policy_types = _policy_resource_types()
    missing = sorted(inventory - policy_types)
    assert not missing, f"persistent types with NO storage policy: {missing}"
    stale = sorted(policy_types - inventory)
    assert not stale, f"policies not mapping to any persistent type: {stale}"


def test_inventory_derives_from_repo_not_a_hardcoded_list():
    """The gate's inventory is REAL: repos.py stores, literal alembic tables,
    and loop-style alembic tables all appear, so a new repository or table
    without a policy fails the gate."""
    gate = _load_gate_module()
    stores = gate.repo_store_names(ROOT)
    tables = gate.alembic_table_names(ROOT)
    # BaseRepository store declared in repositories/repos.py
    assert "storage_descriptors" in stores
    assert "campaigns" in stores
    # literal CREATE TABLE IF NOT EXISTS in a migration
    assert "consent_receipts" in tables
    assert "storage_descriptors" in tables
    # loop-style migration (TABLES = [...] rendered via f-string)
    assert "agent_objectives" in tables
    inventory = gate.persistent_resource_inventory(ROOT)
    assert stores <= inventory and tables <= inventory


def test_gate_fails_when_a_type_loses_its_policy():
    """Simulate adding a persistent type without a policy: coverage math must
    report it missing (the exact condition the CI gate fails on)."""
    gate = _load_gate_module()
    inventory = gate.persistent_resource_inventory(ROOT)
    policy_types = _policy_resource_types()
    without_one = policy_types - {"storage_descriptors"}
    missing = inventory - without_one
    assert "storage_descriptors" in missing


def test_registry_is_enforced_and_schema_complete():
    import yaml

    data = yaml.safe_load((ROOT / "config" / "storage_policies.yaml").read_text())
    assert data["enforcement_status"] == "enforced"
    gate = _load_gate_module()
    for policy in data["policies"]:
        missing = [f for f in gate.REQUIRED_FIELDS if f not in policy]
        assert not missing, f"{policy.get('resource_type')}: missing {missing}"
        if policy["retention_class"] == "legal":
            assert policy["delete_behavior"] != "hard_delete", (
                f"{policy['resource_type']}: legal data must not hard_delete"
            )
