"""Campaign-source auto-link orchestration over ad platform sources (additive, WS-2).

The advertising connect flow stores each connected ad platform as a row in the
canonical ``measurement_connectors`` store — the storage the measurement ad
connector runtime actually reads at sync time. This module owns the additive
campaign-service orchestration over those rows:

* **canonical platform resolution** — a raw platform string (brand name, alias,
  boundary id) resolves through ``campaign.normalization.normalize_platform``
  then the single boundary alias map
  (``shared.integration_contracts.aliases``) to a measurement-backed ad family;
* **idempotent connect** — at most one *active* source per tenant/family.
  Credential sets are required complete at connect because the connector store
  has no config-update path: storing a partial set would create an unfixable
  source (honesty invariant — see ``connect_ad_source``);
* **redacted read model** — the overview surface never returns ``config``; it
  projects non-secret facts (account id, secret-configured, sync/health state);
* **account selection** — manifests have no account discovery
  (``accounts=Accounts()``), so each source is a single manually-entered
  account. ``set_source_account`` *rotates* an active source to a new account
  by archiving the old row (disable) and creating a fresh active row that
  carries the same credentials forward — the only supported config change.
* **disable / enable** — status toggles over the connector store; enabling is
  refused when another active row already exists for the same family so the
  one-active-per-family invariant holds.

Boundary note: this module *anchors* a source (registers it in the connector
store and returns its redacted read model). Ambiguous campaign resolution —
deciding which canonical Aether campaign an external provider campaign maps to
— stays in the existing ``/v1/mapping-review`` surface; this module does not
duplicate that review logic.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from services.campaign.normalization import normalize_platform
from services.measurement.connectors.ad_accounts import (
    AD_ACCOUNT_FAMILIES,
    account_field_for,
    account_value_for,
    is_ad_account_family,
)
from shared.integration_contracts.aliases import canonical_family_id

# Repository surface this orchestration needs (MeasurementConnectorRepository
# methods) — declared structurally so tests can inject a fakes repo.
RepoLike = Any  # measurement.repositories.measurement_connector_repo.MeasurementConnectorRepository

# Status vocabulary used by the connector store.
_STATUS_ACTIVE = "active"
_STATUS_DISABLED = "disabled"


# ── Canonical platform resolution ─────────────────────────────────────────

def resolve_ad_family(raw: Optional[str]) -> Optional[str]:
    """Resolve a raw platform string to a measurement-backed ad family.

    Applies campaign brand normalization first (``facebook``/``adwords`` →
    canonical), then the single boundary alias map (``twitter_ads`` →
    ``x_ads``), then requires a measurement runtime behind the family. Returns
    ``None`` for unknown platforms, alias-only families
    (``snapchat_ads``/``pinterest_ads``), or non-ad families — surfaces then
    never claim a connect for something with no runtime behind it.
    """
    normalized = normalize_platform(raw)
    if not normalized:
        return None
    canonical = canonical_family_id(normalized)
    if not is_ad_account_family(canonical):
        return None
    return canonical


# ── Catalog-derived field truth (lazy — campaign service may import catalog) ─

def _manifest_for(family: str):
    """Lazily load the unified catalog ad manifest for ``family``."""
    from shared.integration_contracts.catalog import manifest_from_ad_platform

    return manifest_from_ad_platform(family)


def _credential_fields(family: str) -> list[dict[str, Any]]:
    """Public credential-field descriptors for ``family`` from the catalog.

    Field shape only (name/type/secret/required) — never values.
    """
    manifest = _manifest_for(family)
    return [
        {
            "name": field.name,
            "type": field.type,
            "secret": field.secret,
            "required": field.required,
        }
        for field in manifest.authentication.credential_schema
    ]


def _secret_fields(family: str) -> list[str]:
    return [f["name"] for f in _credential_fields(family) if f["secret"]]


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


# ── Redacted source read model ───────────────────────────────────────────

def project_source(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project a connector-store row into a redacted campaign-source view.

    ``config`` (which holds credential values) is NEVER returned. Ad families
    additionally surface their single-account facts and secret-configuration
    state; non-ad measurement connector rows project with those fields null so
    the overview stays honest for every stored source type.
    """
    family = row.get("connector_type") or row.get("platform") or ""
    config: Mapping[str, Any] = row.get("config") or {}
    status = row.get("status") or _STATUS_ACTIVE

    view: dict[str, Any] = {
        "connector_id": row.get("connector_id"),
        "platform": family,
        "connector_type": family,
        "name": row.get("name"),
        "status": status,
        "enabled": status == _STATUS_ACTIVE,
        "health_status": row.get("health_status", "unknown"),
        "health_message": row.get("health_message"),
        "last_sync_at": row.get("last_sync_at"),
        "last_success_at": row.get("last_success_at"),
        "next_sync_at": row.get("next_sync_at"),
        "sync_run_count": row.get("sync_run_count", 0),
        "error_count": row.get("error_count", 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        # Ad-family enrichment (null for non-ad rows):
        "is_ad_platform": is_ad_account_family(family),
        "account_field": account_field_for(family),
        "account_id": account_value_for(family, config),
        "secret_configured": None,
        "missing_secrets": [],
        "secrets_total": 0,
    }

    if is_ad_account_family(family):
        secret_fields = _secret_fields(family)
        missing = [name for name in secret_fields if _is_blank(config.get(name))]
        view["secret_configured"] = len(missing) == 0
        view["missing_secrets"] = missing
        view["secrets_total"] = len(secret_fields)

    return view


# ── Overview ─────────────────────────────────────────────────────────────

async def overview_sources(repo: RepoLike, *, tenant_id: str) -> dict[str, Any]:
    """Redacted overview of every campaign source for the tenant."""
    rows = await repo.list_for_tenant(tenant_id)
    items = [project_source(row) for row in rows]
    active = sum(1 for item in items if item["enabled"])
    families = sorted(
        {item["platform"] for item in items if item.get("is_ad_platform")}
    )
    return {
        "items": items,
        "counts": {
            "total": len(items),
            "active": active,
            "disabled": len(items) - active,
            "ad_families": len(families),
        },
        "ad_families": families,
    }


# ── Ad connect options ──────────────────────────────────────────────────

async def ad_connect_options(repo: RepoLike, *, tenant_id: str) -> list[dict[str, Any]]:
    """Describe the ad platforms a tenant can connect, with connect state.

    Iterates the measurement-backed ad families in catalog order. Each option
    carries the platform's public credential-field descriptors (shape only) and
    whether the tenant already has an *active* source for that family (a new
    connect would be idempotent and return that source).
    """
    rows = await repo.list_by_tenant(tenant_id)
    active_families = {
        row.get("connector_type")
        for row in rows
        if row.get("status") == _STATUS_ACTIVE and is_ad_account_family(row.get("connector_type"))
    }

    options: list[dict[str, Any]] = []
    for family in AD_ACCOUNT_FAMILIES:
        manifest = _manifest_for(family)
        options.append({
            "family": family,
            "display_name": manifest.display_name,
            "category": manifest.category,
            "account_field": account_field_for(family),
            "account_discovery": bool(manifest.accounts.discovery_supported),
            "credential_fields": _credential_fields(family),
            "already_connected": family in active_families,
        })
    return options


# ── Idempotent connect ──────────────────────────────────────────────────

def _validate_connect_config(family: str, config: Mapping[str, Any]) -> list[str]:
    """Return the config keys that are blank but required for a complete set.

    Ad sources are single-account and the connector store has no config-update
    path, so a partial connect would persist an unfixable source. Rejecting it
    here (all catalog-schema fields present, incl. the account identifier) is
    the honest edge guard: every stored ad source is fully credentialled.
    """
    missing: list[str] = []
    for field in _credential_fields(family):
        if field["required"] and _is_blank(config.get(field["name"])):
            missing.append(field["name"])
    # The account identifier is a schema field for every family (customer_id,
    # ad_account_id, advertiser_id, account_id); a source with no account would
    # write spend with an empty external_account_id. Named explicitly so the
    # manual single-account requirement is surfaced, not implied.
    account_field = account_field_for(family)
    if account_field and account_field not in missing and _is_blank(config.get(account_field)):
        missing.append(account_field)
    return missing


async def connect_ad_source(
    repo: RepoLike,
    *,
    tenant_id: str,
    platform: str,
    name: Optional[str] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Connect (idempotently) one ad-platform source for the tenant.

    Raises ``ValueError`` for an unsupported platform, an incomplete credential
    set, or a non-ad source type. If the tenant already has an *active* source
    for the family, returns it unchanged (``already_connected=True``) — config
    is never silently overwritten; credential changes require disable +
    re-connect.
    """
    family = resolve_ad_family(platform)
    if not family:
        raise ValueError(
            f"Unsupported ad platform {platform!r}: not a measurement-backed "
            "ad family"
        )
    config = dict(config or {})

    active_rows = await repo.list_by_tenant(
        tenant_id, status=_STATUS_ACTIVE, connector_type=family
    )
    if active_rows:
        existing = project_source(active_rows[0])
        return {
            "already_connected": True,
            "platform": family,
            "source": existing,
            "message": (
                f"An active {family} source already exists; connect is "
                "idempotent. To change credentials, disable it and connect anew."
            ),
        }

    missing = _validate_connect_config(family, config)
    if missing:
        raise ValueError(
            f"Incomplete {family} credential set — missing required "
            f"field(s): {', '.join(sorted(missing))}. Ad sources are "
            "single-account and cannot be partially configured."
        )

    display_label = name
    if not display_label:
        manifest = _manifest_for(family)
        display_label = manifest.display_name

    created = await repo.create(
        tenant_id=tenant_id,
        connector_type=family,
        name=display_label,
        config=dict(config or {}),
    )
    return {
        "already_connected": False,
        "platform": family,
        "source": project_source(created),
    }


# ── Account selection (single-account rotation) ─────────────────────────

async def set_source_account(
    repo: RepoLike,
    *,
    tenant_id: str,
    connector_id: str,
    account_id: str,
) -> dict[str, Any]:
    """Select the single account an active ad source is bound to.

    The account identifier lives inside the source's ``config`` and the
    connector store has no config-update path, so changing it is a *rotation*:
    the current active row is archived (disabled) and a fresh active row is
    created carrying the same credentials forward under the new account. The
    archived row stays visible as honest history. Requesting the account the
    source already has is a no-op.
    """
    row = await repo.get(tenant_id, connector_id)
    if row is None:
        raise ValueError(f"Campaign source {connector_id} not found")

    family = row.get("connector_type") or ""
    if not is_ad_account_family(family):
        raise ValueError(
            f"Source {connector_id} is not an ad-platform source "
            f"({family!r}); account selection does not apply"
        )

    account_field = account_field_for(family)
    desired = (account_id or "").strip()
    if not desired:
        raise ValueError(f"An account id is required for {family} (config key {account_field!r})")

    current = account_value_for(family, row.get("config") or {})
    if current == desired:
        return {
            "connector_id": connector_id,
            "platform": family,
            "account_id": desired,
            "unchanged": True,
            "status": row.get("status", _STATUS_ACTIVE),
        }

    if row.get("status") != _STATUS_ACTIVE:
        raise ValueError(
            f"Source {connector_id} is not active; enable it first or connect "
            "a new source for the new account"
        )

    # Rotate: archive the current source, carry its credentials to a new
    # active row under the new account.
    await repo.set_status(tenant_id, connector_id, _STATUS_DISABLED)
    new_config = dict(row.get("config") or {})
    new_config[account_field] = desired

    created = await repo.create(
        tenant_id=tenant_id,
        connector_type=family,
        name=row.get("name"),
        config=new_config,
    )
    return {
        "connector_id": created["connector_id"],
        "platform": family,
        "account_id": desired,
        "account_rotated": True,
        "status": _STATUS_ACTIVE,
        "superseded_connector_id": connector_id,
        "source": project_source(created),
    }


# ── Disable / enable ────────────────────────────────────────────────────

async def set_source_enabled(
    repo: RepoLike,
    *,
    tenant_id: str,
    connector_id: str,
    enabled: bool,
) -> dict[str, Any]:
    """Disable or enable a campaign source.

    Enabling is refused when another *active* row already exists for the same
    ad family: the one-active-per-family invariant (which connect and account
    rotation both rely on) would otherwise be broken by re-enabling an archived
    row. The caller should connect a fresh source instead.
    """
    row = await repo.get(tenant_id, connector_id)
    if row is None:
        raise ValueError(f"Campaign source {connector_id} not found")

    target_status = _STATUS_ACTIVE if enabled else _STATUS_DISABLED
    current_status = row.get("status", _STATUS_ACTIVE)
    if current_status == target_status:
        return {
            "connector_id": connector_id,
            "platform": row.get("connector_type"),
            "status": current_status,
            "unchanged": True,
        }

    family = row.get("connector_type") or ""
    if enabled and is_ad_account_family(family):
        active_rows = await repo.list_by_tenant(
            tenant_id, status=_STATUS_ACTIVE, connector_type=family
        )
        others_active = [r for r in active_rows if r.get("connector_id") != connector_id]
        if others_active:
            raise ValueError(
                f"Cannot enable {connector_id}: an active {family} source "
                "already exists. Disable it or connect a fresh source instead."
            )

    await repo.set_status(tenant_id, connector_id, target_status)
    return {
        "connector_id": connector_id,
        "platform": row.get("connector_type"),
        "status": target_status,
        "enabled": enabled,
    }


__all__ = [
    "ad_connect_options",
    "connect_ad_source",
    "overview_sources",
    "project_source",
    "resolve_ad_family",
    "set_source_account",
    "set_source_enabled",
]
