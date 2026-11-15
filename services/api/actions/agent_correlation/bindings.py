"""Account bindings derived from verified provider connections.

A binding scopes provider object IDs to an account. Where the tenant has a
verified connection for a provider family, the binding comes from it and
carries the provider account record as its ``verification_ref``; a match on an
object scoped that way is a deterministic binding. Where it does not, a
binding can only come from the tenant's declaration and carries no
verification, so a match on it is graded ``TENANT_DECLARED``.

The verification rule is the provider runtime's own (``object_refs``): the
account and its connection belong to the tenant, share the provider identity,
the connection was verified and is not revoked or failed, the account is one
the connection selected, and its external ID and realm are recorded.

When a family has verified accounts, a request or declaration naming another
account of that family is rejected: a caller cannot scope records to an
account the tenant never verified by naming it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from actions.agent_correlation.mappers._common import AccountBinding, MappingError
from shared.integration_contracts.identity import parse_identity
from shared.integration_contracts.lifecycle import ConnectionState

_REALMS = ("live", "test")
_UNUSABLE_STATES = frozenset({
    ConnectionState.REVOKED,
    ConnectionState.DISABLED,
    ConnectionState.FAILED,
    ConnectionState.REAUTHORIZATION_REQUIRED,
    ConnectionState.DEPRECATED,
    ConnectionState.UNSUPPORTED,
})


@dataclass
class ResolvedBindings:
    defaults: dict[str, AccountBinding] = field(default_factory=dict)
    verified: dict[tuple[str, str], AccountBinding] = field(default_factory=dict)

    def describe(self) -> list[dict[str, Any]]:
        rows = []
        for family, binding in sorted(self.defaults.items()):
            rows.append({
                "provider_family": family,
                "source_account_realm": binding.source_account_realm,
                "verified": binding.verified,
                "binding_source": "verified_connection" if binding.verified else "tenant_declared",
            })
        return rows


def _parse_requested(raw: Optional[Mapping[str, Any]]) -> dict[str, AccountBinding]:
    out: dict[str, AccountBinding] = {}
    for family, value in (raw or {}).items():
        if not isinstance(value, Mapping) or not str(value.get("source_account_key") or "").strip():
            raise MappingError(f"account binding for {family!r} needs source_account_key")
        realm = str(value.get("source_account_realm") or "live")
        if realm not in _REALMS:
            raise MappingError("source_account_realm must be live or test")
        out[str(family)] = AccountBinding(str(value["source_account_key"]).strip(), realm)
    return out


def verified_in_other_realm(verified: Mapping[tuple[str, str, str], AccountBinding], family: str,
                            account_key: str, realm: str) -> bool:
    """True when ``account_key`` is verified for ``family`` only in another realm."""
    return any(f == family and k == account_key and r != realm for f, r, k in verified)


class BindingResolver:
    def __init__(self, *, accounts: Any = None, connections: Any = None, declared: Any = None) -> None:
        self._accounts = accounts
        self._connections = connections
        self._declared = declared

    def _account_repo(self) -> Any:
        if self._accounts is None:
            from connectors.provider_runtime.acquisition import ProviderAccountRepository

            self._accounts = ProviderAccountRepository()
        return self._accounts

    def _connection_repo(self) -> Any:
        if self._connections is None:
            from connectors.provider_runtime.connection import ProviderConnectionRepository

            self._connections = ProviderConnectionRepository()
        return self._connections

    async def verified_accounts(self, tenant_id: str) -> dict[tuple[str, str, str], AccountBinding]:
        """Verified bindings keyed ``(family, realm, account_key)``: one provider
        account ID can be verified in both the live and the test realm."""
        out: dict[tuple[str, str, str], AccountBinding] = {}
        for connection in await self._connection_repo().list_for_tenant(tenant_id, limit=200):
            if (
                connection.tenant_id != tenant_id
                or not connection.last_verified_at
                or connection.state in _UNUSABLE_STATES
            ):
                continue
            try:
                family = str(parse_identity(connection.provider_identity).family)
            except Exception:  # noqa: BLE001 - an unparseable identity is simply not a verified scope
                continue
            for selected in connection.selected_accounts:
                account = await self._account_repo().find(f"{connection.connection_id}:{selected}")
                if account is None:
                    continue
                realm = account.metadata.get("source_account_realm")
                if not all((
                    account.tenant_id == tenant_id,
                    account.connection_id == connection.connection_id,
                    account.provider_identity == connection.provider_identity,
                    bool(account.external_id),
                    realm in _REALMS,
                )):
                    continue
                out[(family, str(realm), str(account.external_id))] = AccountBinding(
                    source_account_key=str(account.external_id),
                    source_account_realm=str(realm),
                    verification_ref=account.account_id,
                )
        return out

    async def resolve(self, tenant_id: str, requested: Optional[Mapping[str, Any]] = None) -> ResolvedBindings:
        verified = await self.verified_accounts(tenant_id)
        families_verified: dict[str, list[AccountBinding]] = {}
        for (family, _realm, _key), binding in verified.items():
            families_verified.setdefault(family, []).append(binding)

        declared: dict[str, AccountBinding] = {}
        if self._declared is not None:
            declared = await self._declared.all_for(tenant_id)

        def scoped(family: str, candidate: AccountBinding, *, strict: bool) -> Optional[AccountBinding]:
            match = verified.get((family, candidate.source_account_realm, candidate.source_account_key))
            if match is not None:
                return match
            if verified_in_other_realm(verified, family, candidate.source_account_key,
                                       candidate.source_account_realm):
                raise MappingError(f"{family} account is verified for a different realm")
            if family in families_verified:
                if strict:
                    raise MappingError(f"{family} account is not a verified connection for this tenant")
                return None  # a stale declaration never overrides verified scope
            return candidate

        defaults: dict[str, AccountBinding] = {
            family: accounts[0] for family, accounts in families_verified.items() if len(accounts) == 1
        }
        for family, binding in declared.items():
            chosen = scoped(family, binding, strict=False)
            if chosen is not None:
                defaults[family] = chosen
        for family, binding in _parse_requested(requested).items():
            chosen = scoped(family, binding, strict=True)
            if chosen is not None:
                defaults[family] = chosen
        return ResolvedBindings(defaults=defaults, verified=verified)
