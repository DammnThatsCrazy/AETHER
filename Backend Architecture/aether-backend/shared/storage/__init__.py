"""
Aether Shared — Elastic Data Plane storage layer (FT-7-STORAGE-DESCRIPTORS).

Public surface:
  - StorageDescriptor           universal handle for any externalized object
  - ObjectStore protocol        put/get/head/delete/list (S3 or in-memory)
  - StorageManager              policy-driven externalize/hydrate
  - reconcile / ReconciliationReport
                                descriptor-vs-object drift detection

Policies live in config/storage_policies.yaml (repo root) — one policy per
persistent resource type, enforced by scripts/release/check_storage_policies.py.
"""

from shared.storage.descriptor import (  # noqa: F401
    DESCRIPTOR_SCHEMA_VERSION,
    StorageDescriptor,
    sha256_hex,
)
from shared.storage.manager import (  # noqa: F401
    ChecksumMismatchError,
    StorageManager,
    StoragePolicy,
    StoragePolicyViolationError,
    UnknownResourceTypeError,
    load_storage_policies,
    policy_for,
)
from shared.storage.object_store import (  # noqa: F401
    InMemoryObjectStore,
    ObjectNotFoundError,
    ObjectStat,
    ObjectStore,
    S3ObjectStore,
    get_object_store,
)
from shared.storage.reconciler import (  # noqa: F401
    ReconciliationReport,
    reconcile,
    reconcile_object_store,
)
