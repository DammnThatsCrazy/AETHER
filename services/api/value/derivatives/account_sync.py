"""Sync linked venue accounts through the provider raw admission path.

One sync reads one linked account with its venue adapter (read-only, bounded,
checkpointed) and, for every account event:

1. wraps it as a :class:`RawProviderRecord` for the link's connection and
   account (``provider-account:<connection_id>:<account_ref>``);
2. persists it with :class:`RawProviderRecordStore`, which asks the Rights
   Authority first and holds the link's grant unrevoked across the write;
3. writes the canonical fill (fills only today) to ``derivatives_fills`` with
   the admitting ``source_id``, grant and rights decision in ``source_refs``.

A denied admission stops the sync for that link without advancing its
checkpoint, so nothing after the denial is retained and a later sync after a
re-link starts from the last admitted point. Revoked links and links without a
grant are never read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from shared.common.common import utc_now

SYNC_LINK_LIMIT = 200
SYNC_MAX_PAGES = 5
_ACCOUNT_EVENT_TYPES = {
    "derivatives_fill_observed": "fill",
    "derivatives_position_opened_observed": "position",
    "derivatives_position_increased_observed": "position",
    "derivatives_position_reduced_observed": "position",
    "derivatives_position_closed_observed": "position",
    "derivatives_position_liquidated_observed": "position",
}


@dataclass
class LinkSyncResult:
    link_id: str
    status: str
    admitted: int = 0
    fills_written: int = 0
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "status": self.status,
            "admitted": self.admitted,
            "fills_written": self.fills_written,
            "reason": self.reason,
        }


@dataclass
class TenantSyncResult:
    tenant_id: str
    links: list[LinkSyncResult] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "truncated": self.truncated,
            "links": [r.to_dict() for r in self.links],
        }


def _record_id(event: dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    for key in ("fill_id", "position_id", "funding_payment_id", "trading_fee_id"):
        if payload.get(key):
            return str(payload[key])
    return str(event.get("idempotency_key") or event.get("event_id") or "")


def default_adapter_factory(venue: str, account_ref: str, credential: Any = None) -> Any:
    import httpx

    from value.derivatives.adapters import VENUE_ADAPTERS

    adapter_cls = type(VENUE_ADAPTERS[venue])
    return adapter_cls(
        http_transport=httpx.AsyncHTTPTransport(), account_ref=account_ref, max_pages=SYNC_MAX_PAGES,
    )


class VenueAccountSync:
    """Read linked accounts, admit their raw records, write canonical fills."""

    def __init__(
        self,
        *,
        link_service: Any = None,
        raw_store: Any = None,
        fill_repo: Any = None,
        adapter_factory: Optional[Callable[..., Any]] = None,
        provisioner: Any = None,
    ) -> None:
        self._links = link_service
        self._raw_store = raw_store
        self._fills = fill_repo
        self._factory = adapter_factory or default_adapter_factory
        self._provisioner = provisioner

    def _link_service(self) -> Any:
        if self._links is None:
            from value.derivatives.account_links import VenueAccountLinkService

            self._links = VenueAccountLinkService()
        return self._links

    def _store(self) -> Any:
        if self._raw_store is None:
            from connectors.provider_runtime.raw_store import RawProviderRecordStore

            self._raw_store = RawProviderRecordStore()
        return self._raw_store

    def _fill_repo(self) -> Any:
        if self._fills is None:
            from repositories.derivatives_repos import FillRepo

            self._fills = FillRepo()
        return self._fills

    def _sources(self) -> Any:
        if self._provisioner is None:
            from value.derivatives.venue_sources import VenueSourceProvisioner

            self._provisioner = VenueSourceProvisioner()
        return self._provisioner

    async def _credential(self, link: Any) -> Any:
        if not link.credential_ref:
            return None
        from connectors.provider_runtime.credential_broker import credential_broker

        return await credential_broker.reveal(link.tenant_id, link.credential_ref)

    async def sync_tenant(self, tenant_id: str) -> TenantSyncResult:
        links = await self._link_service().list_links(tenant_id)
        result = TenantSyncResult(tenant_id=tenant_id, truncated=len(links) > SYNC_LINK_LIMIT)
        for link in links[:SYNC_LINK_LIMIT]:
            result.links.append(await self.sync_link(link))
        return result

    async def sync_link(self, link: Any) -> LinkSyncResult:
        from connectors.provider_runtime.rights_admission import ProviderRawRightsDenied
        from value.derivatives.account_links import LinkMethod, LinkStatus

        if link.status is not LinkStatus.ACTIVE:
            return LinkSyncResult(link.link_id, "skipped", reason="link_revoked")
        if not (link.grant_id and link.connection_id and link.source_id):
            return LinkSyncResult(link.link_id, "skipped", reason="link_not_governed")
        if link.method is LinkMethod.TENANT_PUSH:
            # The tenant forwards this account's activity itself; nothing to pull.
            return LinkSyncResult(link.link_id, "skipped", reason="tenant_push_link")

        # The checkpoint lives on the link row and belongs to its connection: a
        # re-link (new connection and grant) starts a fresh read.
        state = dict(link.sync_state or {})
        checkpoint = state.get("checkpoint") if state.get("connection_id") == link.connection_id else None
        try:
            adapter = self._factory(link.venue, link.account_ref, await self._credential(link))
            events, next_checkpoint = await adapter.pull_events(checkpoint)
        except Exception:  # noqa: BLE001 - one venue outage never fails the sweep
            return LinkSyncResult(link.link_id, "failed", reason="venue_read_failed")

        result = LinkSyncResult(link.link_id, "ok")
        for event in events:
            kind = _ACCOUNT_EVENT_TYPES.get(str(event.get("event_name") or ""))
            if kind is None:
                continue
            try:
                admission = await self._admit(link, kind, event)
            except ProviderRawRightsDenied:
                # Stop here: nothing after a denial is retained, and the
                # checkpoint stays where the last admitted sync left it.
                result.status, result.reason = "denied", "rights_denied"
                return result
            result.admitted += 1
            if kind == "fill" and await self._write_fill(link, event, admission):
                result.fills_written += 1

        await self._link_service().record_sync_state(link.tenant_id, link.link_id, {
            "connection_id": link.connection_id,
            "checkpoint": next_checkpoint,
            "provider_health": next_checkpoint.get("provider_health"),
            "synced_at": utc_now().isoformat(),
        })
        if next_checkpoint.get("provider_health") not in (None, "ok"):
            result.status, result.reason = "degraded", str(next_checkpoint.get("provider_health"))
        elif link.method is not LinkMethod.WALLET_PROOF:
            await self._sources().mark_verified(tenant_id=link.tenant_id, connection_id=link.connection_id)
        return result

    async def _admit(self, link: Any, kind: str, event: dict[str, Any]) -> dict[str, Any]:
        from shared.integration_contracts.events import make_raw_record

        from value.derivatives.venue_sources import venue_profile

        record = make_raw_record(
            provider_identity=venue_profile(link.venue).account_identity,
            tenant_id=link.tenant_id,
            connection_id=link.connection_id,
            account_id=link.account_ref,
            provider_record_type=kind,
            provider_record_id=_record_id(event),
            payload=event,
            provider_occurred_at=(event.get("payload") or {}).get("executed_at"),
        )
        ((stored, _was_new),) = await self._store().ingest([record], tenant_id=link.tenant_id)
        return dict((stored.metadata or {}).get("aether_rights_admission") or {})

    async def _write_fill(self, link: Any, event: dict[str, Any], admission: dict[str, Any]) -> bool:
        from value.derivatives.runtime_routes import _fill_source_refs
        from value.derivatives.foundation import deterministic_idempotency_key

        payload = dict(event.get("payload") or {})
        fill_id = payload.get("fill_id")
        if not fill_id:
            return False
        refs = _fill_source_refs(payload)
        for key in ("source_id", "source_grant_ref", "rights_decision_ref"):
            if admission.get(key):
                refs.append(f"{key}={admission[key]}")
        repo = self._fill_repo()
        record = {
            "tenant_id": link.tenant_id,
            "idempotency_key": deterministic_idempotency_key(
                f"{link.tenant_id}|derivatives_fill_observed|{fill_id}|"
            ),
            "execution_by_aether": False,
            **{k: v for k, v in payload.items() if k != "execution_by_aether"},
            "source_refs": refs,
        }
        record = {k: v for k, v in record.items() if k in repo.columns}
        return bool(await repo.insert(record))


__all__ = ["LinkSyncResult", "TenantSyncResult", "VenueAccountSync", "default_adapter_factory"]
