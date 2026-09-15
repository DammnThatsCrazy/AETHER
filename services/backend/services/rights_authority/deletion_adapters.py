"""Aether — Rights Authority: deletion adapters (the execution half of retention).

``services.rights_authority.retention`` computes an expiry and persists a
**pending** ``delete_at_expiry`` impact item; it deletes nothing. This module is
the adapter seam that can turn such an impact row into a real store deletion,
and ``services.rights_authority.deletion_executor`` is the sweep that drives it.

Doctrine (fail closed, no fake completion):

- An adapter is registered ONLY for a store that genuinely has a delete path
  today. The byte plane — ``shared.storage.object_store.ObjectStore.delete(key)``
  — is that store. Every other cascade dimension is declared **UNSUPPORTED**
  (:data:`UNSUPPORTED_DIMENSION_REASONS`) and keeps its impact rows ``pending``.
  There is deliberately no stub adapter that reports a success it did not
  achieve: a fabricated completion is worse than an unresolved row.
- Every adapter must be able to prove, before deleting, that the artifact
  reference sits inside the impact's own tenant scope
  (:meth:`DeletionAdapter.validate_scope`). A reference that cannot be proven
  in-scope is refused, never deleted.
- The registry exposes an adapter-presence check (:meth:`has_adapter`) so the
  executor can gate on it rather than catching an exception.

Tenant scoping reuses the canonical byte-plane guard already proven by the Data
Exchange expire path (``services.data_exchange.jobs_ops.
validate_object_key_for_delete``): a key is deletable only when it is
well-shaped AND rooted at the operating tenant's own
``data-exchange/<tenant>/`` prefix (trailing-slash guarded, so ``acme`` never
matches ``acme2``). The guard is imported, not re-implemented — a second,
divergent scope validator is exactly the parallel authority the rights blueprint
forbids. The consequence is a deliberate, honest limitation: a ``raw_object``
ref that is not a well-shaped data-exchange object key is REFUSED (row stays
``pending``) rather than deleted on trust, because no other key scheme carries a
provable tenant scope in the byte plane today.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Protocol, runtime_checkable

from shared.logger.logger import get_logger
from services.rights_authority.impact import RIGHTS_IMPACT_DIMENSIONS

logger = get_logger("aether.rights_irrl.deletion_adapters")

# Deletion outcomes (canonical tokens; a caller must never infer success from
# anything else).
DELETION_STATUS_DELETED = "deleted"
DELETION_STATUS_ALREADY_ABSENT = "already_absent"
DELETION_STATUS_REFUSED_OUT_OF_SCOPE = "refused_out_of_scope"

# The one dimension with a real, tenant-scoped delete path today.
BYTE_PLANE_DIMENSION = "raw_object"


@dataclass(frozen=True)
class DeletionResult:
    """Outcome of one adapter delete attempt.

    ``deleted`` is True only when this call removed bytes. ``already_absent``
    (bytes were already gone) still satisfies a retention obligation and is
    reported as its own status rather than being counted as a deletion — the
    executor records what actually happened, never what it hoped happened.
    """

    status: str
    deleted: bool
    reason: str = ""
    evidence_refs: tuple[str, ...] = ()


@runtime_checkable
class DeletionAdapter(Protocol):
    """A store that can delete one artifact within one tenant scope.

    ``component_type`` is the ``RIGHTS_IMPACT_DIMENSIONS`` value this adapter
    serves; the registry is keyed by it.

    ``validate_scope`` must return the tenant-scoped reference it is safe to
    delete, or ``None`` to refuse. It is a pure predicate (no I/O) so the
    executor can refuse BEFORE it claims or mutates any durable state.

    ``delete`` performs the irreversible removal, and must itself re-validate
    the scope (an adapter is never trusted to delete a reference it could not
    prove in-scope, even when called directly rather than through the sweep).
    """

    component_type: str

    def validate_scope(self, *, tenant_id: str, artifact_ref: str) -> Optional[str]: ...

    async def delete(self, *, tenant_id: str, artifact_ref: str) -> DeletionResult: ...


def validate_object_key_for_tenant(tenant_id: str, key: object) -> Optional[str]:
    """Return ``key`` when the byte plane may delete it for ``tenant_id``.

    Delegates to the canonical Data Exchange guard. Returns ``None`` to refuse:
    a malformed key, a key outside ``data-exchange/<tenant>/``, or a tenant id
    the guard itself rejects (which raises upstream) all mean "not provably in
    scope", and a caller must never delete on a ``None`` return.
    """
    from services.data_exchange.jobs_ops import validate_object_key_for_delete

    try:
        return validate_object_key_for_delete(tenant_id, key)
    except Exception as exc:  # noqa: BLE001 — an unusable tenant id refuses, never deletes
        logger.warning(
            "deletion refused: tenant scope unprovable for tenant=%r key=%r (%s)",
            tenant_id,
            key,
            exc,
        )
        return None


class ObjectStoreDeletionAdapter:
    """Byte-plane deletion adapter (``data-exchange/<tenant>/...`` object keys).

    Deletes through ``ObjectStore.delete(key)``. The store is resolved lazily so
    a missing or misconfigured backend surfaces as an error on the delete (the
    row is then marked ``blocked``) rather than at import time.
    """

    component_type = BYTE_PLANE_DIMENSION

    def __init__(self, store: object = None) -> None:
        self._store = store

    def _resolve_store(self):
        if self._store is not None:
            return self._store
        from shared.storage.object_store import get_object_store  # lazy

        return get_object_store()

    def validate_scope(self, *, tenant_id: str, artifact_ref: str) -> Optional[str]:
        return validate_object_key_for_tenant(tenant_id, artifact_ref)

    async def delete(self, *, tenant_id: str, artifact_ref: str) -> DeletionResult:
        key = self.validate_scope(tenant_id=tenant_id, artifact_ref=artifact_ref)
        if key is None:
            return DeletionResult(
                status=DELETION_STATUS_REFUSED_OUT_OF_SCOPE,
                deleted=False,
                reason="out_of_tenant_key_scope",
            )
        store = self._resolve_store()
        if store.head(key) is None:
            # Already gone: the retention obligation is satisfied, but nothing
            # was deleted by this call and that is what gets reported.
            return DeletionResult(
                status=DELETION_STATUS_ALREADY_ABSENT,
                deleted=False,
                reason="object_absent_from_byte_plane",
            )
        store.delete(key)
        return DeletionResult(
            status=DELETION_STATUS_DELETED,
            deleted=True,
            reason="byte_plane_delete",
            evidence_refs=(f"objdel:{key}",),
        )


# ═══════════════════════════════════════════════════════════════════════════
# Explicitly UNSUPPORTED dimensions
# ═══════════════════════════════════════════════════════════════════════════
# Every cascade dimension without a registered adapter is declared here with the
# concrete reason it cannot be executed today. Declaring a dimension is
# mandatory: the module-level invariant below refuses to import if a dimension
# is neither served by an adapter nor declared, so a new dimension can never
# silently fall through to "nothing happened, assume it's fine".
UNSUPPORTED_DIMENSION_REASONS: dict[str, str] = {
    "normalized_row": (
        "no tenant-scoped delete keyed by artifact_ref: normalized rows are "
        "addressed by row id through BaseRepository.delete, which is not "
        "tenant-scoped; remediation there is recompute/upsert, not removal"
    ),
    "graph_edge": (
        "graph state is mutated only through the graph mutation gateway/ledger; "
        "there is no rights-side per-edge delete path"
    ),
    "vector_embedding": (
        "embeddings are recomputed/overwritten by their owning pipeline; no "
        "delete path is exposed to the rights authority"
    ),
    "cached_result": (
        "cached results are owned by their cache TTL/eviction path, which "
        "removes them without a rights-facing per-key delete"
    ),
    "derived_profile_attribute": (
        "derived attributes are recomputed from their sources; no delete path "
        "is exposed to the rights authority"
    ),
    "exported_artifact": (
        "exported artifacts are governed by the export plane's own expiry sweep "
        "(services.export); no per-artifact delete hook is exposed to the rights "
        "authority"
    ),
    "model_training_input": (
        "training inputs are remediated by retrain/evaluation in the model "
        "governance path, not by deleting stored bytes"
    ),
    "generalized_artifact": (
        "generalized artifacts are remediated by re-checking eligibility and "
        "re-deriving through the Generalization Gateway, not by deletion"
    ),
}


class DeletionAdapterRegistry:
    """Adapter registry keyed by ``component_type``, with a presence check."""

    def __init__(self, adapters: Iterable[DeletionAdapter] = ()) -> None:
        self._adapters: dict[str, DeletionAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: DeletionAdapter) -> DeletionAdapter:
        component_type = str(getattr(adapter, "component_type", "") or "")
        if component_type not in RIGHTS_IMPACT_DIMENSIONS:
            raise ValueError(
                f"deletion adapter for unknown component_type {component_type!r}; "
                f"expected one of {', '.join(RIGHTS_IMPACT_DIMENSIONS)}"
            )
        if component_type in self._adapters:
            raise ValueError(
                f"duplicate deletion adapter for component_type {component_type!r}"
            )
        self._adapters[component_type] = adapter
        return adapter

    def get(self, component_type: Optional[str]) -> Optional[DeletionAdapter]:
        """The adapter serving ``component_type``, or ``None`` when unsupported."""
        return self._adapters.get(str(component_type or ""))

    def has_adapter(self, component_type: Optional[str]) -> bool:
        """Whether a real delete path exists for ``component_type``."""
        return self.get(component_type) is not None

    def supported_dimensions(self) -> tuple[str, ...]:
        """Registered dimensions, in cascade order."""
        return tuple(d for d in RIGHTS_IMPACT_DIMENSIONS if d in self._adapters)

    def unsupported_dimensions(self) -> tuple[str, ...]:
        """Dimensions with no delete path, in cascade order."""
        return tuple(d for d in RIGHTS_IMPACT_DIMENSIONS if d not in self._adapters)

    def unsupported_reason(self, component_type: Optional[str]) -> Optional[str]:
        """The declared reason this dimension has no delete path, if it has none."""
        if self.has_adapter(component_type):
            return None
        return UNSUPPORTED_DIMENSION_REASONS.get(str(component_type or ""))


def _assert_every_dimension_is_declared() -> None:
    """Import-time invariant: every cascade dimension is supported or declared.

    Fail closed at import rather than at deletion time — a dimension that is
    neither served nor declared has no honest answer to "did this get deleted?".
    """
    undeclared = sorted(
        d
        for d in RIGHTS_IMPACT_DIMENSIONS
        if d not in UNSUPPORTED_DIMENSION_REASONS and d != BYTE_PLANE_DIMENSION
    )
    if undeclared:
        raise RuntimeError(
            "deletion adapters: cascade dimensions neither supported nor declared "
            f"unsupported: {undeclared}"
        )


_assert_every_dimension_is_declared()


def build_default_deletion_adapters() -> tuple[DeletionAdapter, ...]:
    """The adapters whose stores genuinely have a delete path today."""
    return (ObjectStoreDeletionAdapter(),)


# Module-level default registry used by the deletion executor. Tests and callers
# may pass their own registry; nothing else is wired by importing this module.
deletion_adapter_registry = DeletionAdapterRegistry(build_default_deletion_adapters())


__all__ = [
    "BYTE_PLANE_DIMENSION",
    "DELETION_STATUS_ALREADY_ABSENT",
    "DELETION_STATUS_DELETED",
    "DELETION_STATUS_REFUSED_OUT_OF_SCOPE",
    "UNSUPPORTED_DIMENSION_REASONS",
    "DeletionAdapter",
    "DeletionAdapterRegistry",
    "DeletionResult",
    "ObjectStoreDeletionAdapter",
    "build_default_deletion_adapters",
    "deletion_adapter_registry",
    "validate_object_key_for_tenant",
]
