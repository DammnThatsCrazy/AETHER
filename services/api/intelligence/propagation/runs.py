"""Saved propagation runs: persistence, staleness and recompute.

A saved run is derived intelligence. It keeps the query, the computed run and
its inputs (the grants of the fills it used and a digest of the linked
population). Reading it back checks those inputs against the current state:

* ``source_grant_revoked`` — a grant behind one of its fills is no longer active;
* ``linked_population_changed`` — links were added, revoked or reassigned.

A stale run is still returned (it is a record of what was computed), marked
``stale`` with its reasons; ``recompute`` runs the same query again and saves
the new run with ``supersedes`` pointing at the old one. Nothing here writes
graph truth.
"""

from __future__ import annotations

from typing import Any, Optional

from intelligence.propagation.contracts import ExposureChannel, PropagationQuery, PropagationRun
from shared.common.common import utc_now

SAVED_RUN_LIST_LIMIT = 100


def query_from_dict(data: dict[str, Any]) -> PropagationQuery:
    fields = dict(data)
    fields["instrument_keys"] = tuple(fields.get("instrument_keys") or ())
    fields["channels"] = tuple(ExposureChannel(c) for c in (fields.get("channels") or ()))
    return PropagationQuery(**fields)


def _subject_refs(run: dict[str, Any]) -> list[str]:
    """Every subject a run names (adopters, seeds, path ends, hops, signals)."""
    refs: set[str] = set()

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, k)
        elif isinstance(value, list):
            for item in value:
                walk(item, key)
        elif isinstance(value, str) and value and (
            key.endswith("_subject")
            or key in ("subject_id", "subject_ids", "subjects", "subject_refs",
                       "lockstep_groups", "shared_funding_pairs")
        ):
            refs.add(value)

    walk(run.get("episodes") or [])
    return sorted(refs)


class PropagationRunStore:
    def __init__(
        self, *, repo: Any = None, link_service: Any = None, grant_service: Any = None,
        service_factory: Any = None,
    ) -> None:
        self._repo = repo
        self._links = link_service
        self._grants = grant_service
        self._service_factory = service_factory

    def _repository(self) -> Any:
        if self._repo is None:
            from repositories.repos import PropagationRunRepository

            self._repo = PropagationRunRepository()
        return self._repo

    def _link_service(self) -> Any:
        if self._links is None:
            from value.derivatives.account_links import VenueAccountLinkService

            self._links = VenueAccountLinkService()
        return self._links

    def _grant_service(self) -> Any:
        if self._grants is None:
            from connectors.integrations.data_rights.service import data_rights_service

            self._grants = data_rights_service
        return self._grants

    def _service(self) -> Any:
        if self._service_factory is not None:
            return self._service_factory()
        from intelligence.propagation.service import PropagationService

        return PropagationService()

    async def save(
        self, run: PropagationRun, inputs: Any, *, include_live: bool, supersedes: Optional[str] = None,
    ) -> dict[str, Any]:
        body = run.to_dict()
        record = {
            "run_id": run.run_id,
            "tenant_id": run.tenant_id,
            "query": body["query"],
            "run": body,
            "include_live": include_live,
            "grant_refs": list(getattr(inputs, "grant_refs", ()) or ()),
            "population_digest": getattr(inputs, "population_digest", None),
            "subject_refs": _subject_refs(body),
            "supersedes": supersedes,
            "saved_at": utc_now().isoformat(),
        }
        existing = await self._repository().get_for_tenant(run.tenant_id, run.run_id)
        if existing is None:
            await self._repository().insert(run.run_id, record)
        else:
            await self._repository().update(run.run_id, {**existing, **record})
        return record

    async def list(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = await self._repository().list_for_tenant(tenant_id, limit=SAVED_RUN_LIST_LIMIT)
        return [
            {k: r.get(k) for k in ("run_id", "saved_at", "include_live", "supersedes", "query")}
            for r in sorted(rows, key=lambda r: str(r.get("saved_at") or ""), reverse=True)
        ]

    async def get(self, tenant_id: str, run_id: str) -> Optional[dict[str, Any]]:
        record = await self._repository().get_for_tenant(tenant_id, run_id)
        if record is None:
            return None
        reasons = await self._staleness(tenant_id, record)
        return {**record, "stale": bool(reasons), "stale_reasons": reasons}

    async def _staleness(self, tenant_id: str, record: dict[str, Any]) -> list[str]:
        from intelligence.propagation.service import population_digest

        reasons: list[str] = []
        for grant_id in record.get("grant_refs") or []:
            grant = await self._grant_service().get_grant(grant_id, tenant_id=tenant_id)
            status = getattr(getattr(grant, "status", None), "value", getattr(grant, "status", None))
            if grant is None or status != "active" or getattr(grant, "revoked_at", None) is not None:
                reasons.append("source_grant_revoked")
                break
        try:
            current, _ = await self._link_service().subjects_by_account_bounded(tenant_id)
        except Exception:  # noqa: BLE001 - unknown is reported, never assumed fresh
            reasons.append("linked_population_unverifiable")
        else:
            if population_digest(current) != record.get("population_digest"):
                reasons.append("linked_population_changed")
        return reasons

    async def recompute(self, tenant_id: str, run_id: str) -> Optional[dict[str, Any]]:
        record = await self._repository().get_for_tenant(tenant_id, run_id)
        if record is None:
            return None
        query = query_from_dict(record["query"])
        if query.tenant_id != tenant_id:
            return None
        service = self._service()
        run = await service.run(query, include_live=bool(record.get("include_live")))
        return await self.save(run, service.last_inputs, include_live=bool(record.get("include_live")),
                               supersedes=run_id)

    async def erase_subject(self, tenant_id: str, subject_id: str) -> int:
        return await self._repository().delete_naming_subject(tenant_id, subject_id)


__all__ = ["PropagationRunStore", "query_from_dict"]
