"""Defensive, injectable source readers for the Communication360 provider (Phase 4).

The ``communication360`` projection is read-only over canonical Aether truth.
Its provider (``services/communication360/provider.py``) never crashes and never
fabricates: every section is rendered from rows the sources actually returned,
and an unavailable backing source DEGRADES the affected section to a typed
``degraded`` / ``missing`` state instead of inventing numbers or leaking an
exception body.

This module defines the narrow read seam the provider depends on:
:class:`CommunicationSource` (the protocol), two concrete sources, and a
``default_sources()`` factory:

* :class:`SilverCommsSource` — the shipped message spine. It wraps
  ``services/comms`` ``CommsFactsRepository`` and maps silver rows (dicts over
  that repository's ``_FACT_COLUMNS``) idempotently onto the frozen
  :class:`~services.communication360.contracts.CommunicationMessage` view. It
  works whether the repo is backed by PostgreSQL or by its in-memory fallback
  (``AETHER_ENV=local``). An EMPTY silver source is a valid *available* source
  (a real zero), which is distinct from an UNAVAILABLE backing pool — the
  provider treats those differently.
* :class:`CanonicalFactSource` — the Phase-3 canonical-authority fact store
  (``Communication360FactsRepository``). ``facts()`` returns the stored dict
  rows filtered by ``kind``; ``messages()`` returns ``[]`` because messages
  come from the silver path, never duplicated here.

Imports stay light and side-effect free: constructing a source never opens a
connection (the repositories only touch their backing pool when a read is
called), and every read is wrapped so a failure returns ``[]`` / ``False`` —
the provider degrades, it never raises and never fabricates.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from repositories.repos import get_pool

# These imports load repository modules only — no connection is opened until a
# read is actually issued (and reads fall back to in-memory stores when the
# pool is None, so no database is required to run or test the reader).
from services.comms.contracts import CommunicationState
from services.comms.repository import CommsFactsRepository
from services.communication360.contracts import CommunicationMessage
from services.communication360.repository import Communication360FactsRepository
from services.operational_intelligence.models import EvidenceRef
from shared.contracts_models.epistemic import EpistemicStatus

#: Canonical ``source`` string carried by every silver EvidenceRef the message
#: reader synthesizes (the row is itself the observed fact).
_SILVER_SOURCE = "services/comms/silver_comms_facts"


# ─────────────────────────────────────────────────────────────────────────────
# Protocol
# ─────────────────────────────────────────────────────────────────────────────


class CommunicationSource:
    """Tenant-scoped communication read seam (messages + canonical facts).

    Implementations MUST be tenant-scoped and defensive. The provider trusts
    nothing and re-filters every returned row by the requesting tenant, but a
    source that cannot reach its backing store returns ``[]`` / ``False`` —
    never raises, never fabricates. An EMPTY result from a reachable source is a
    valid *available* zero; an UNAVAILABLE source is reported through
    :meth:`available`.
    """

    async def messages(
        self,
        tenant_id: str,
        *,
        campaign_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[CommunicationMessage]:
        """Typed message-spine rows for the tenant (optionally one campaign)."""
        raise NotImplementedError

    async def facts(
        self,
        tenant_id: str,
        *,
        kind: Optional[str] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Raw fact rows for the tenant, optionally filtered by ``kind``."""
        raise NotImplementedError

    async def available(self, tenant_id: str) -> bool:
        """True when the backing store responds (even with zero rows)."""
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
# Idempotent silver-row -> CommunicationMessage mapping
# ─────────────────────────────────────────────────────────────────────────────


def _first_present(row: dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value) != "":
            return str(value)
    return None


def _coerce_communication_state(value: Any) -> Optional[CommunicationState]:
    """A ``communication_state`` column value -> the typed member, or None.

    ``None`` (never a fabricated member) when the column holds an unknown /
    legacy string that is not a member of :class:`CommunicationState` — the row
    is still a valid observed message, its lifecycle state is just unclassified.
    """
    if value is None:
        return None
    if isinstance(value, CommunicationState):
        return value
    try:
        return CommunicationState(str(value))
    except ValueError:
        return None


def _coerce_evidence_refs(row: dict[str, Any]) -> list[EvidenceRef]:
    """Reused EvidenceRefs carried by a silver row (dedup, stable order).

    A silver row may already carry ``evidence_ids``; each becomes an
    ``event`` EvidenceRef. The row's own fact identity is always the final
    grounding ref when nothing more specific is present — a row that was
    observed is itself evidence of the observation.
    """
    refs: list[EvidenceRef] = []
    seen: set[str] = set()
    observed_at = _first_present(row, "occurred_at", "received_at")

    def _add(eid: Optional[str], source: str) -> None:
        if not eid or eid in seen:
            return
        seen.add(eid)
        refs.append(
            EvidenceRef(
                id=eid,
                type="event",
                source=source,
                observedAt=observed_at,
                uri=f"store://silver_comms_facts/{eid}",
            )
        )

    evidence_ids = row.get("evidence_ids")
    ids: list[Any] = []
    if isinstance(evidence_ids, list):
        ids = evidence_ids
    elif isinstance(evidence_ids, str) and evidence_ids.strip():
        try:
            parsed = json.loads(evidence_ids)
            ids = parsed if isinstance(parsed, list) else [evidence_ids]
        except json.JSONDecodeError:
            ids = [evidence_ids]
    for eid in ids:
        _add(str(eid), _SILVER_SOURCE)

    row_id = _first_present(row, "fact_id", "source_event_id", "canonical_activity_key")
    _add(row_id, _SILVER_SOURCE)
    return refs


def to_message(row: dict[str, Any]) -> CommunicationMessage:
    """Map one silver row dict idempotently onto the frozen CommunicationMessage.

    The same row always maps to the same message: ``fact_id`` -> ``fact_id``,
    ``message_id``/``canonical_activity_key`` -> canonical ``message_id``,
    ``communication_state`` string -> the typed value (or None when the string
    is not a member of :class:`CommunicationState`). Comm can only report what
    the row observed, so ``claim_state`` is capped at ``EpistemicStatus.OBSERVED``.
    """
    tenant_id = _first_present(row, "tenant_id") or ""
    fact_id = _first_present(row, "fact_id")
    message_id = _first_present(row, "message_id", "canonical_activity_key")
    if message_id is None:
        # No canonical message identity in the row — fall back to the fact id
        # so the view stays valid and deterministic (never a fabricated id).
        message_id = f"fact:{fact_id}" if fact_id else f"silver:{tenant_id}"

    occurred_at = _first_present(row, "occurred_at", "received_at") or ""
    return CommunicationMessage(
        message_id=message_id,
        tenant_id=tenant_id,
        fact_id=fact_id,
        provider=_first_present(row, "provider"),
        provider_event_id=_first_present(row, "provider_event_id"),
        external_message_id=_first_present(row, "external_message_id"),
        external_thread_id=_first_present(row, "external_thread_id"),
        channel=_first_present(row, "channel") or "email",
        direction=_first_present(row, "direction"),
        communication_state=_coerce_communication_state(row.get("communication_state")),
        sender_entity_id=_first_present(row, "sender_entity_id"),
        recipient_entity_id=_first_present(row, "recipient_entity_id"),
        recipient_alias_id=_first_present(row, "recipient_alias_id"),
        subject=None,
        content_ref=None,
        campaign_id=_first_present(row, "campaign_id"),
        occurred_at=occurred_at,
        received_at=_first_present(row, "received_at"),
        claim_state=EpistemicStatus.OBSERVED,
        evidence_refs=_coerce_evidence_refs(row),
    )


def _as_utc(value: Optional[str]) -> Optional[datetime]:
    """Best-effort ISO string -> aware datetime (None when unparseable)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# SilverCommsSource — shipped message spine over CommsFactsRepository
# ─────────────────────────────────────────────────────────────────────────────


class SilverCommsSource:
    """Message-spine source over the shipped ``silver_comms_facts`` path.

    Wraps :class:`~services.comms.repository.CommsFactsRepository`. Rows are
    read tenant-scoped (optionally narrowed to one ``campaign_id``) and mapped
    to :class:`CommunicationMessage`. The repository has no dedicated
    chronological tenant/campaign scan, so this adapter performs the scan over
    the same two backings the repository uses — the module in-memory store
    when the pool is ``None`` (mirroring ``services/comms/routes.py``) and the
    ``silver_comms_facts`` table through ``get_pool()`` when one exists. The
    adapter never raises: a failed backing read returns ``[]`` and
    :meth:`available` reports the store unreachable.
    """

    def __init__(self, repo: Optional[CommsFactsRepository] = None) -> None:
        self._repo = repo if repo is not None else CommsFactsRepository()

    # ── CommunicationSource ────────────────────────────────────────────────

    async def messages(
        self,
        tenant_id: str,
        *,
        campaign_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[CommunicationMessage]:
        rows = await self._rows(tenant_id, campaign_id=campaign_id, since=since, limit=limit)
        # Provider-side tenant guard is server-authoritative; a misbehaving
        # store can never leak another tenant's messages through this source.
        rows = [r for r in rows if str(r.get("tenant_id", "")) == str(tenant_id)]
        messages = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                messages.append(to_message(row))
            except Exception:  # noqa: BLE001 - skip an un-mappable row, never crash
                continue
        return messages

    async def facts(
        self,
        tenant_id: str,
        *,
        kind: Optional[str] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Raw silver rows for the tenant.

        The silver path has no canonical ``kind`` discriminator, so ``kind`` is
        interpreted as a ``source_event_type`` / ``communication_state`` /
        ``message_category`` match when provided (honest: a canonical fact kind
        that does not exist on the silver path returns no rows).
        """
        rows = await self._rows(tenant_id, campaign_id=None, since=since, limit=limit)
        if kind is not None:
            rows = [
                r for r in rows
                if str(r.get("source_event_type") or "") == kind
                or str(r.get("communication_state") or "") == kind
                or str(r.get("message_category") or "") == kind
            ]
        return [r for r in rows if str(r.get("tenant_id", "")) == str(tenant_id)]

    async def available(self, tenant_id: str) -> bool:
        """True when the silver backing responds (even with zero rows).

        An EMPTY silver source is a valid *available* source; only a pool that
        cannot be reached reports ``False``.
        """
        try:
            pool = await get_pool()
        except Exception:  # noqa: BLE001 - unreachable pool -> unavailable
            return False
        if pool is None:
            return True  # the in-memory store is always reachable
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:  # noqa: BLE001 - reachability probe failed
            return False

    # ── Row scan ───────────────────────────────────────────────────────────

    async def _rows(
        self,
        tenant_id: str,
        *,
        campaign_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Tenant-scoped silver rows, chronological ascending. Never raises."""
        try:
            pool = await get_pool()
        except Exception:  # noqa: BLE001 - backing unavailable -> []
            return []
        if pool is None:
            return self._memory_rows(tenant_id, campaign_id=campaign_id, since=since, limit=limit)
        return await self._db_rows(pool, tenant_id, campaign_id=campaign_id, since=since, limit=limit)

    @staticmethod
    def _memory_rows(
        tenant_id: str,
        *,
        campaign_id: Optional[str],
        since: Optional[str],
        limit: Optional[int],
    ) -> list[dict[str, Any]]:
        # Local/test path — same module store the CommsFactsRepository writes,
        # read directly (established routes.py precedent for tenant scans).
        from services.comms.repository import _local_facts  # noqa: WPS433

        rows = [
            r for r in _local_facts.values()
            if str(r.get("tenant_id", "")) == str(tenant_id)
            and (campaign_id is None or str(r.get("campaign_id") or "") == str(campaign_id))
            and (since is None or str(r.get("occurred_at") or "") >= str(since))
        ]
        rows.sort(key=lambda r: (str(r.get("occurred_at") or ""), str(r.get("fact_id") or "")))
        if limit is not None:
            rows = rows[: max(0, int(limit))]
        return rows

    @staticmethod
    async def _db_rows(
        pool: Any,
        tenant_id: str,
        *,
        campaign_id: Optional[str],
        since: Optional[str],
        limit: Optional[int],
    ) -> list[dict[str, Any]]:
        params: list[Any] = [tenant_id]
        where = ["tenant_id = $1"]
        if campaign_id is not None:
            params.append(str(campaign_id))
            where.append(f"campaign_id = ${len(params)}")
        if since is not None:
            since_dt = _as_utc(since)
            if since_dt is not None:
                params.append(since_dt)
                where.append(f"occurred_at >= ${len(params)}")
        sql = (
            "SELECT * FROM silver_comms_facts "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY occurred_at ASC, fact_id ASC"
        )
        if limit is not None:
            params.append(max(0, int(limit)))
            sql += f" LIMIT ${len(params)}"
        try:
            async with pool.acquire() as conn:
                records = await conn.fetch(sql, *params)
        except Exception:  # noqa: BLE001 - backing unavailable -> degrade
            return []
        return [dict(r) for r in records]


# ─────────────────────────────────────────────────────────────────────────────
# CanonicalFactSource — Phase-3 canonical fact store
# ─────────────────────────────────────────────────────────────────────────────


class CanonicalFactSource:
    """Canonical-authority fact source over ``Communication360FactsRepository``.

    ``facts()`` returns the stored dict rows (filtered by ``kind`` /
    ``since`` / ``limit``) that the repository already tenants-scopes.
    ``messages()`` returns ``[]`` — the message spine comes from the silver
    path and is never duplicated in the canonical store.
    """

    def __init__(self, repo: Optional[Communication360FactsRepository] = None) -> None:
        self._repo = repo if repo is not None else Communication360FactsRepository()

    async def messages(
        self,
        tenant_id: str,
        *,
        campaign_id: Optional[str] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[CommunicationMessage]:
        return []  # messages come from the silver path

    async def facts(
        self,
        tenant_id: str,
        *,
        kind: Optional[str] = None,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        try:
            rows = await self._repo.query(tenant_id, kind=kind, since=since, limit=limit)
        except Exception:  # noqa: BLE001 - backing unavailable -> degrade
            return []
        # Tenant-scoped by the repo; re-filter defensively (trust nothing).
        return [r for r in rows if str(r.get("tenant_id", "")) == str(tenant_id)]

    async def available(self, tenant_id: str) -> bool:
        try:
            await self._repo.query(tenant_id, limit=1)
            return True
        except Exception:  # noqa: BLE001 - unreachable backing -> unavailable
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────


def default_sources() -> dict[str, CommunicationSource]:
    """The production default source set: ``{"silver": ..., "canonical": ...}``."""
    return {
        "silver": SilverCommsSource(),
        "canonical": CanonicalFactSource(),
    }


__all__ = [
    "CanonicalFactSource",
    "CommunicationSource",
    "SilverCommsSource",
    "default_sources",
    "to_message",
]
