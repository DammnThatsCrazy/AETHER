"""Subject / artifact impact indexes (prompt §3.12).

Reverse indexes that let a DSR discover *what to touch* before propagation runs:

* :class:`SubjectIndex`  — ``subject_ref -> {component: [record_ids]}``.
* :class:`ArtifactIndex` — ``subject_ref -> [artifacts]`` and the artifact's
  declared subject set.

Both are tenant-scoped (``tenant_id`` is the first argument of every helper and
every stored/queried row) so impact discovery can never cross tenants. Rows use
deterministic ids so re-recording the same mapping is idempotent (no dup rows).

Storage reuses the JSONB-backed :class:`_ScopedRepo`; ``find_many`` only supports
equality filters, so mappings are stored as *flat pair rows* (one row per
subject/component/record and one row per artifact/subject) which equality
filters can query directly.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from shared.common.common import BadRequestError

from services.security.repositories import _ScopedRepo

from .models import DSR_COMPONENTS, now_iso


def _digest(*parts: str) -> str:
    """Stable short hash of the given parts for idempotent row ids."""
    joined = "\x1f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]


# ══════════════════════════════════════════════════════════════════════════════
# SUBJECT INDEX — subject_ref -> component -> record_ids
# ══════════════════════════════════════════════════════════════════════════════

class DSRSubjectIndexRepository(_ScopedRepo):
    """Table ``dsr_subject_index``. One row per (tenant, subject, component, record)."""

    def __init__(self) -> None:
        super().__init__("dsr_subject_index")


class SubjectIndex:
    """Maps a subject to the concrete records that reference it, per component."""

    def __init__(self, repo: Optional[DSRSubjectIndexRepository] = None) -> None:
        self._repo = repo or DSRSubjectIndexRepository()

    async def record_subject_ref(
        self, tenant_id: str, subject_ref: str, component: str, record_id: str,
    ) -> dict:
        """Index one record that holds data for ``subject_ref`` under ``component``.

        Idempotent: the same (tenant, subject, component, record) upserts one row.
        Fail-closed on missing identifiers or an unknown component.
        """
        if not tenant_id:
            raise BadRequestError("tenant_id is required")
        if not subject_ref:
            raise BadRequestError("subject_ref is required")
        if not record_id:
            raise BadRequestError("record_id is required")
        if component not in DSR_COMPONENTS:
            raise BadRequestError(
                f"Invalid component {component!r}. Allowed: {list(DSR_COMPONENTS)}"
            )

        row_id = f"sidx_{_digest(tenant_id, subject_ref, component, record_id)}"
        data = {
            "id": row_id,
            "tenant_id": tenant_id,
            "subject_ref": subject_ref,
            "component": component,
            "record_id": record_id,
            "recorded_at": now_iso(),
        }
        existing = await self._repo.find_by_id(row_id)
        if existing:
            return await self._repo.update(row_id, data)
        return await self._repo.insert(row_id, data)

    async def find_impacted(
        self, tenant_id: str, subject_ref: str,
    ) -> dict[str, list[str]]:
        """Return ``{component: [record_ids]}`` for every record indexed to a subject.

        Tenant-scoped: only rows for ``tenant_id`` are returned, so a subject_ref
        that also exists under another tenant is never surfaced here. Record ids
        are de-duplicated and sorted for deterministic output.
        """
        if not tenant_id or not subject_ref:
            return {}
        rows = await self._repo.list_for_tenant(
            tenant_id, limit=10_000, extra={"subject_ref": subject_ref},
        )
        impacted: dict[str, set[str]] = {}
        for row in rows:
            component = row.get("component")
            record_id = row.get("record_id")
            if not component or not record_id:
                continue
            impacted.setdefault(component, set()).add(record_id)
        return {component: sorted(ids) for component, ids in sorted(impacted.items())}


# ══════════════════════════════════════════════════════════════════════════════
# ARTIFACT INDEX — artifact <-> subjects (derived artifacts: exports, models, ...)
# ══════════════════════════════════════════════════════════════════════════════

class DSRArtifactIndexRepository(_ScopedRepo):
    """Table ``dsr_artifact_index``. One row per (tenant, artifact, subject) pair."""

    def __init__(self) -> None:
        super().__init__("dsr_artifact_index")


class ArtifactIndex:
    """Maps derived artifacts (exports, model_artifacts, replay_bundles, ...) to
    the subjects whose data they embed, and back."""

    def __init__(self, repo: Optional[DSRArtifactIndexRepository] = None) -> None:
        self._repo = repo or DSRArtifactIndexRepository()

    async def record_artifact(
        self, tenant_id: str, artifact_id: str, kind: str, subject_refs: list[str],
    ) -> list[dict]:
        """Index an artifact of ``kind`` as containing data for ``subject_refs``.

        Stores one flat pair row per subject so ``artifacts_for_subject`` can be
        answered with an equality filter. Idempotent per (artifact, subject).
        Returns the stored/updated pair rows.
        """
        if not tenant_id:
            raise BadRequestError("tenant_id is required")
        if not artifact_id:
            raise BadRequestError("artifact_id is required")
        if not kind:
            raise BadRequestError("kind is required")

        stored: list[dict] = []
        for subject_ref in subject_refs or []:
            if not subject_ref:
                continue
            row_id = f"aidx_{_digest(tenant_id, artifact_id, subject_ref)}"
            data = {
                "id": row_id,
                "tenant_id": tenant_id,
                "artifact_id": artifact_id,
                "kind": kind,
                "subject_ref": subject_ref,
                "recorded_at": now_iso(),
            }
            existing = await self._repo.find_by_id(row_id)
            if existing:
                stored.append(await self._repo.update(row_id, data))
            else:
                stored.append(await self._repo.insert(row_id, data))
        return stored

    async def artifacts_for_subject(
        self, tenant_id: str, subject_ref: str,
    ) -> list[dict]:
        """Return ``[{artifact_id, kind}]`` for every artifact embedding a subject.

        Tenant-scoped and de-duplicated (an artifact indexed twice appears once),
        sorted by ``artifact_id`` for deterministic output.
        """
        if not tenant_id or not subject_ref:
            return []
        rows = await self._repo.list_for_tenant(
            tenant_id, limit=10_000, extra={"subject_ref": subject_ref},
        )
        by_artifact: dict[str, str] = {}
        for row in rows:
            artifact_id = row.get("artifact_id")
            if not artifact_id:
                continue
            by_artifact[artifact_id] = row.get("kind", "")
        return [
            {"artifact_id": artifact_id, "kind": kind}
            for artifact_id, kind in sorted(by_artifact.items())
        ]

    async def subjects_for_artifact(
        self, tenant_id: str, artifact_id: str,
    ) -> list[str]:
        """Return the sorted subject_refs an artifact embeds (tenant-scoped)."""
        if not tenant_id or not artifact_id:
            return []
        rows = await self._repo.list_for_tenant(
            tenant_id, limit=10_000, extra={"artifact_id": artifact_id},
        )
        return sorted({r.get("subject_ref") for r in rows if r.get("subject_ref")})
