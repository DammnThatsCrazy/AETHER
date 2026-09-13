"""Declared capabilities — the tenant's intended capability surface (PR 2, Phase B2, §9.3/§9.5).

A **declaration** is a tenant asserting "this capability is one we intend to have." It is
the side that observed capabilities (``capability_catalog``) are compared against to
produce drift.

**A declaration is not evidence about the publisher.** Nothing here — and nothing anywhere
in this backend — verifies who published a third-party MCP server or provider tool. A
declaration says only what *this tenant* asserted, and the assertion is worth exactly as
much as the operator who typed it. So there is no ``verified`` state, no ``trusted`` flag,
and no field that could be read as "someone checked this" (see ``identity.py``, which
refuses to create one for the same reason).

What a declaration *does* buy is a fixed point to compare against:

* ``capability_id`` is computed with ``models.capability_id_for`` over the **same** tuple
  ``(tenant, provider, server_key, tool_name)`` that the observed catalog uses, so the
  declaration↔observation join is exact — no fuzzy name matching, no heuristics that
  could silently pair a declaration with the wrong observed row.
* ``artifact_digest`` is computed with ``identity.artifact_digest_for`` over the declared
  identity tuple, so §9.5 drift is a digest comparison rather than a field-by-field
  guess. ``digest_map()`` is the single read Phase C needs.

Storage invariants:

1. ``declaration_id`` is deterministic (``identity.declaration_id_for``), so ``declare``
   is an **upsert**. Two rows for one capability would each report their own drift
   verdict, and an operator reading a "declared / drifted" pair would have no way to tell
   which one is the tenant's actual position.
2. A declaration must identify *something* — at least one of ``server_name`` /
   ``server_url`` / ``tool_name``. An empty declaration would hash to the same
   deterministic id as every other empty declaration in the tenant and would silently
   overwrite it.
3. ``server_url`` is passed through ``catalog_service._sanitize_server_url`` before it is
   stored. A declaration is a durable, operator-readable row served back over the API; a
   ``user:pass@`` or ``?token=`` URL must not land in it just because a human pasted one.
4. Reads and withdraws compare ``tenant_id`` and raise ``NotFoundError`` on mismatch, so a
   declaration id cannot be used to confirm another tenant's row exists.

Records are flat (no nesting) because ``BaseRepository`` stores the dict as JSONB and
filters on **top-level** ``data->>'key'`` only — and because DSR erasure by ``tenant_id``
goes through ``delete_by_entity`` on that same top-level field.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.common.common import BadRequestError, NotFoundError, utc_now
from shared.logger.logger import get_logger
from services.security.repositories import _ScopedRepo

from . import identity
from .catalog_service import _clean, _sanitize_server_url, _server_key
from .models import capability_id_for

logger = get_logger("aether.service.agent_access_intelligence.declarations")

CAPABILITY_DECLARATIONS_TABLE = "capability_declarations"

# The fields whose values define "which artifact this is". Enumerated here (rather than
# taken from the request body wholesale) so that the dict handed to
# ``identity.artifact_digest_for`` carries exactly the keys ``identity._identity_tuple``
# reads — an extra field must never be able to change a stored digest.
_IDENTITY_FIELDS = (
    "provider",
    "server_name",
    "server_url",
    "tool_name",
    "protocol_version",
    "capability_kind",
)


class CapabilityDeclarationRepository(_ScopedRepo):
    """``capability_declarations`` rows (JSONB-backed; in-memory for local/dev/tests).

    Store name matches the alembic table (``20260806_capability_declarations``) and its
    ``storage_policies.yaml`` ``resource_type`` entry exactly — the storage-policy gate
    derives its inventory from those table names."""

    def __init__(self) -> None:
        super().__init__(CAPABILITY_DECLARATIONS_TABLE)

    async def list_declarations(
        self,
        tenant_id: str,
        *,
        provider: Optional[str] = None,
        server_name: Optional[str] = None,
        capability_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        extra: dict[str, Any] = {}
        if provider:
            extra["provider"] = provider
        if server_name:
            extra["server_name"] = server_name
        if capability_id:
            extra["capability_id"] = capability_id
        return await self.list_for_tenant(tenant_id, limit=limit, offset=offset, extra=extra or None)


class CapabilityDeclarationService:
    """Declare / read / withdraw a tenant's intended capabilities.

    Deliberately holds no comparison logic: it produces the declared side and exposes
    ``digest_map`` so drift is computed in one place (Phase C), not derived twice from two
    modules that could disagree."""

    def __init__(self, repo: Optional[CapabilityDeclarationRepository] = None) -> None:
        self._repo = repo or CapabilityDeclarationRepository()

    # ── writes ────────────────────────────────────────────────────────────────

    async def declare(
        self,
        *,
        tenant_id: str,
        declared_by_entity_id: str,
        provider: Optional[str] = None,
        server_name: Optional[str] = None,
        server_url: Optional[str] = None,
        tool_name: Optional[str] = None,
        protocol_version: Optional[str] = None,
        capability_kind: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Upsert the tenant's declaration for one capability.

        Re-declaring the same ``(provider, server, tool)`` updates the existing row rather
        than adding a second one — see invariant 1 in the module docstring."""
        if not tenant_id or not str(tenant_id).strip():
            raise BadRequestError("tenant_id is required")

        fields: dict[str, Any] = {
            "provider": _clean(provider),
            "server_name": _clean(server_name),
            # Sanitized BEFORE anything derives from it, so neither the stored row nor
            # `publisher_label` (which does not re-sanitize, by design) can carry a
            # credential a human pasted into the URL.
            "server_url": _sanitize_server_url(_clean(server_url)),
            "tool_name": _clean(tool_name),
            "protocol_version": _clean(protocol_version),
            "capability_kind": _clean(capability_kind),
        }

        if not (fields["server_name"] or fields["server_url"] or fields["tool_name"]):
            raise BadRequestError(
                "a declaration must identify a capability: at least one of "
                "server_name, server_url or tool_name is required"
            )

        # Same key the observed catalog uses (`catalog_service._server_key`), so the two
        # sides agree on what "the server" is before either id is derived from it.
        server_key = _server_key(fields)
        declaration_id = identity.declaration_id_for(
            tenant_id, fields["provider"], server_key, fields["tool_name"]
        )

        existing = await self._repo.find_by_id(declaration_id)
        if existing is not None and str(existing.get("tenant_id")) != str(tenant_id):
            # Unreachable: `declaration_id_for` hashes tenant_id, so ids never collide
            # across tenants. Fail closed rather than overwrite a foreign row if it ever
            # becomes reachable.
            raise BadRequestError("declaration id collision")  # pragma: no cover

        now = utc_now().isoformat()
        record: dict[str, Any] = {
            "declaration_id": declaration_id,
            "tenant_id": str(tenant_id),
            # Stored (not recomputed at read time) so Phase C can index declarations by
            # the same key the observed catalog is keyed by.
            "capability_id": capability_id_for(
                tenant_id, fields["provider"], server_key, fields["tool_name"]
            ),
            **{k: fields[k] for k in _IDENTITY_FIELDS},
            "publisher_ref": identity.publisher_ref_for(fields["server_url"], fields["provider"]),
            "publisher_label": identity.publisher_label_for(fields["server_url"], fields["provider"]),
            # A declaration asserts a SUBSET of identity, and drift is only ever measured
            # over that subset. An operator declares what they know — provider, server,
            # tool — and cannot know the `capability_kind` this service derives internally
            # or the `protocol_version` the server speaks today. Digesting the full tuple
            # made every ordinary declaration compare unequal, so the risk surface reported
            # a permanent HIGH "no longer matches what was observed" for capabilities that
            # had never changed. The asserted field list is stored so the observed side can
            # be digested over exactly the same fields at comparison time.
            "declared_fields": identity.asserted_identity_fields(fields),
            "artifact_digest": identity.artifact_digest_for(
                fields, identity.asserted_identity_fields(fields)
            ),
            "declared_by_entity_id": _clean(declared_by_entity_id),
            # First declaration wins for `declared_at`; `updated_at` moves on re-declare,
            # so "when did this tenant first assert this" survives an edit.
            "declared_at": (existing or {}).get("declared_at") or now,
            "updated_at": now,
            "notes": _clean(notes),
        }

        if existing is not None:
            stored = await self._repo.update(declaration_id, record)
        else:
            stored = await self._repo.insert(declaration_id, record)
        return self._public(stored)

    async def withdraw(self, *, tenant_id: str, declaration_id: str) -> dict:
        """Hard-delete a declaration and return the record that was removed.

        Hard delete, not a ``withdrawn`` flag: a withdrawn declaration must stop
        contributing a drift verdict, and a soft-deleted row that ``digest_map`` had to
        remember to filter would eventually be forgotten by some caller."""
        record = await self.get(tenant_id=tenant_id, declaration_id=declaration_id)
        deleted = await self._repo.delete(declaration_id)
        if not deleted:  # pragma: no cover — `get` already proved it exists
            raise NotFoundError("capability_declaration")
        return record

    # ── reads ─────────────────────────────────────────────────────────────────

    async def get(self, *, tenant_id: str, declaration_id: str) -> dict:
        record = await self._repo.find_by_id(declaration_id)
        if not record or str(record.get("tenant_id")) != str(tenant_id):
            # Identical failure for "absent" and "other tenant" so the id cannot be used
            # as an existence oracle.
            raise NotFoundError("capability_declaration")
        return self._public(record)

    async def list(
        self,
        *,
        tenant_id: str,
        provider: Optional[str] = None,
        server_name: Optional[str] = None,
        capability_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        rows = await self._repo.list_declarations(
            tenant_id,
            provider=provider,
            server_name=server_name,
            capability_id=capability_id,
            limit=limit,
            offset=offset,
        )
        return [self._public(r) for r in rows]

    async def digest_map(
        self, tenant_id: str, *, limit: int = 1000
    ) -> tuple[dict[str, dict[str, Any]], bool]:
        """The drift comparison input for one tenant, plus whether the read was truncated.

        Returns ``({capability_id: {"digest": ..., "fields": [...]}}, truncated)``.

        ``fields`` is the identity subset the declaration actually asserted; the caller
        must digest the observed row over the same subset, or every ordinary declaration
        compares unequal and the surface fabricates permanent drift.

        Rows missing either half are **skipped**, never emitted with an empty digest: an
        empty declared digest compares unequal to every observed digest, which
        ``identity.identity_state_for`` would report as ``drifted``. Reporting drift for a
        row we cannot compare would fabricate a finding.

        ``truncated`` is returned rather than swallowed because the failure it prevents is
        silent and one-directional: a declaration outside the window makes its capability
        look ``observed_only``, which is deliberately *not* a finding — so real drift would
        disappear and the caller would be told the scan was clean. Every other bounded read
        in this package discloses when it is hit; this one is no exception.
        """
        rows = await self._repo.list_for_tenant(tenant_id, limit=limit)
        truncated = len(rows) >= limit
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            capability_id = row.get("capability_id")
            digest = row.get("artifact_digest")
            if not capability_id or not digest:
                continue
            out[str(capability_id)] = {
                "digest": str(digest),
                # Declarations written before `declared_fields` existed fall back to the
                # full tuple, which is how they were digested at the time.
                "fields": list(row.get("declared_fields") or identity.IDENTITY_FIELDS),
            }
        return out, truncated

    # ── serialization ─────────────────────────────────────────────────────────

    @staticmethod
    def _public(record: dict[str, Any]) -> dict[str, Any]:
        """API-facing view: private (``_``-prefixed) fields stripped."""
        out = {k: v for k, v in record.items() if not k.startswith("_")}
        out["declaration_id"] = record.get("declaration_id") or record.get("id")
        return out


capability_declaration_service = CapabilityDeclarationService()
