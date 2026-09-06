"""Activation planner — turns activation intents into connect steps (WS-3).

The planner is the tenant-aware half of intent-driven activation. It owns:

* durable persistence of a tenant's chosen :class:`ActivationIntent` tokens on
  the activation record (``tenant_activations.intents``);
* deriving, for each recommended experience category, the per-integration
  connect step — which connect action is next, *from real tenant state* via the
  shared connector config store (never a fabricated step); and
* running one connect action by delegating to ``connector_service`` — the exact
  runtime behind ``PUT /v1/integrations/connectors/{type}`` + ``/test`` +
  ``/sync`` that the Settings surface uses — so credentials flow through the
  credential service and enablement through the consent policy, with no second
  implementation.

State vocabulary: per-integration ``connection_state`` reuses
:class:`shared.integration_contracts.lifecycle.ConnectionState` member values
(the canonical connection machine). No new readiness word is invented here; a
connect step that has not happened is ``available`` and a connected integration
is ``connected`` — never a fabricated "Ready".
"""
from __future__ import annotations

from typing import Any, Optional

from shared.common.common import BadRequestError, ForbiddenError, utc_now
from shared.integration_contracts.experience import ExperienceCategory
from shared.integration_contracts.lifecycle import ConnectionState
from shared.logger.logger import get_logger
from shared.integration_contracts.manifest import ProviderManifest

from services.integrations.connectors.service import connector_service

from .intents import (
    INTENT_ORDER,
    ActivationIntent,
    category_manifests,
    connectable_manifests_for,
    experience_categories_view,
    experience_label,
    intent_catalog,
    intent_description,
    intent_label,
    manifest_to_activation_entry,
    recommended_categories_for,
    valid_intent_tokens,
)
from .repository import ActivationRepository
from .service import ActivationService

logger = get_logger("aether.service.activation.planner")

# Connect actions the activation surface can run. Each maps 1:1 onto a
# connector_service operation (the shared connect contracts), never a second
# implementation.
CREATE_INTEGRATION = "create_tenant_integration"
CONFIGURE_CREDENTIAL = "configure_credential"
ENABLE_CONNECTION = "enable_connection"
FIRST_SYNC = "first_sync"

_CONNECT_ACTIONS: frozenset[str] = frozenset(
    {CREATE_INTEGRATION, CONFIGURE_CREDENTIAL, ENABLE_CONNECTION, FIRST_SYNC}
)


class ActivationPlanner:
    """Tenant-aware activation planner over the one catalog."""

    def __init__(self) -> None:
        self.repo = ActivationRepository()
        # Record lifecycle is owned by ActivationService (the SDK activation
        # machine) — the planner reuses it so intent selections land on the same
        # durable record and state semantics never fork.
        self._activation = ActivationService()

    # ── Record lifecycle (same store as the SDK activation machine) ─────────

    async def _load_or_create(self, tenant_id: str) -> dict[str, Any]:
        return await self._activation._load_or_create(tenant_id)

    # ── Intent selection (durable save/resume) ───────────────────────────────

    async def get_selected_intents(self, tenant_id: str) -> list[str]:
        record = await self._load_or_create(tenant_id)
        return self._canonical_intents(record.get("intents", []))

    @staticmethod
    def _canonical_intents(tokens: list[str]) -> list[str]:
        """Deduplicate + reorder tokens into canonical intent order."""
        present = set(tokens)
        return [i.value for i in INTENT_ORDER if i.value in present]

    async def select_intents(self, tenant_id: str, tokens: list[str]) -> dict[str, Any]:
        """Persist the tenant's intent tokens (validated, canonical order).

        Idempotent: re-selecting replaces the prior set. Unknown tokens raise a
        client error rather than being silently dropped.
        """
        unknown = set(tokens) - valid_intent_tokens()
        if unknown:
            raise BadRequestError(
                f"unknown activation intent(s): {sorted(unknown)}"
            )
        record = await self._load_or_create(tenant_id)
        record["intents"] = self._canonical_intents(list(tokens))
        record["intents_updated_at"] = utc_now().isoformat()
        record = await self.repo.save_or_update(record)
        return self._intent_view(record)

    @staticmethod
    def _intent_view(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "intents": list(record.get("intents", [])),
            "intents_updated_at": record.get("intents_updated_at"),
        }

    # ── Intent picker (catalog metadata, no tenant state) ────────────────────

    async def intent_catalog_view(self) -> dict[str, Any]:
        """The intent picker + the canonical experience-category order/labels."""
        return {
            "intents": intent_catalog(),
            "experience_categories": experience_categories_view(),
        }

    # ── Connect plan derivation (real tenant state only) ─────────────────────

    async def build_plan(self, tenant_id: str) -> dict[str, Any]:
        """The recommended connect plan for the tenant's selected intents.

        No intents selected -> ``needs_selection`` (the UI prompts, never
        fabricates a plan). Otherwise one block per recommended experience
        category (deduplicated across intents, ordered by first recommendation),
        each integration carrying its derived connection state and next action.
        """
        record = await self._load_or_create(tenant_id)
        selected = self._canonical_intents(record.get("intents", []))
        if not selected:
            return {
                "tenant_id": tenant_id,
                "needs_selection": True,
                "selected_intents": [],
                "categories": [],
            }

        rows = await connector_service.repo.find_many(
            filters={"tenant_id": tenant_id}, limit=1000
        )
        rows_by_family = {r.get("connector_type"): r for r in rows}

        ordered_categories: list[ExperienceCategory] = []
        seen: set[ExperienceCategory] = set()
        recommended_by: dict[ExperienceCategory, list[str]] = {}
        for intent in INTENT_ORDER:
            if intent.value not in selected:
                continue
            for category in recommended_categories_for(intent):
                if category not in seen:
                    seen.add(category)
                    ordered_categories.append(category)
                recommended_by.setdefault(category, []).append(intent.value)

        categories = [
            await self._category_plan(
                category,
                rows_by_family,
                recommended_by.get(category, []),
            )
            for category in ordered_categories
        ]

        return {
            "tenant_id": tenant_id,
            "needs_selection": False,
            "selected_intents": selected,
            "intents": [
                {
                    "token": token,
                    "label": intent_label(ActivationIntent(token)),
                    "description": intent_description(ActivationIntent(token)),
                }
                for token in selected
            ],
            "categories": categories,
        }

    async def _category_plan(
        self,
        category: ExperienceCategory,
        rows_by_family: dict[str, dict[str, Any]],
        recommended_by_intents: list[str],
    ) -> dict[str, Any]:
        """One experience-category block of the connect plan.

        Categories with a shared connector_service surface list only the
        actionable integrations (never the payment-rail/ad catalog twins that
        have their own connect flows). A category with no actionable surface
        yet (advertising in a base without the ad connect flow) lists its
        catalog entries honestly as non-actionable.
        """
        actionable = connectable_manifests_for(category)
        if actionable:
            chosen = actionable
        else:
            chosen = [m for m in category_manifests(category)]

        integrations = [
            self._integration_plan_entry(m, rows_by_family.get(m.provider_family))
            for m in chosen
        ]
        connected = sum(
            1
            for it in integrations
            if it["connectable"] and it["connection_state"] == ConnectionState.CONNECTED.value
        )
        return {
            "experience_category": category.value,
            "display_name": experience_label(category),
            "recommended_by_intents": recommended_by_intents,
            "connected_count": connected,
            "integration_count": len(integrations),
            "integrations": integrations,
        }

    def _integration_plan_entry(
        self,
        manifest: ProviderManifest,
        row: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """Project one manifest + tenant row onto a connect-step entry.

        ``connection_state``/``next_action`` derive from REAL tenant facts
        (enabled / secret_configured / sync_status). ``can_act`` is false only
        when the next step cannot honestly be offered (catalog-only connect
        surface, or nothing left to do on a connected/attention integration).
        """
        entry = manifest_to_activation_entry(manifest)
        connectable = entry["connectable"]

        if not connectable:
            # Catalog-available integration whose connect lives elsewhere
            # (advertising/payment-rail flow). No activation connect step is
            # offered — the UI surfaces the honest reason instead.
            entry["connection_state"] = ConnectionState.AVAILABLE.value
            entry["next_action"] = None
            entry["can_act"] = False
            entry["record"] = None
            return entry

        if row is None:
            entry["connection_state"] = ConnectionState.AVAILABLE.value
            entry["next_action"] = CREATE_INTEGRATION
            entry["can_act"] = True
            entry["record"] = None
            return entry

        sync_status = str(row.get("sync_status") or "never_synced")
        enabled = bool(row.get("enabled"))
        secret_configured = bool(row.get("secret_configured"))

        state, next_action, can_act = self._derive_from_facts(
            sync_status, enabled, secret_configured
        )
        entry["connection_state"] = state
        entry["next_action"] = next_action
        entry["can_act"] = can_act
        entry["record"] = {
            "name": row.get("name"),
            "enabled": enabled,
            "secret_configured": secret_configured,
            "sync_status": sync_status,
            "last_synced_at": row.get("last_synced_at"),
            "error_count": row.get("error_count", 0),
        }
        return entry

    @staticmethod
    def _derive_from_facts(
        sync_status: str, enabled: bool, secret_configured: bool
    ) -> tuple[str, Optional[str], bool]:
        """Honest connect-step derivation from connector record facts only.

        A healthy sync is the only evidence that yields ``connected``;
        a credential missing / connector disabled / never synced each map to
        exactly one next action. ``failed``/``degraded`` surfaces an honest
        attention state with no fake forward step.
        """
        if sync_status == "healthy":
            return ConnectionState.CONNECTED.value, None, False
        if sync_status == "syncing":
            return ConnectionState.INITIAL_SYNC_RUNNING.value, None, False
        if sync_status == "failed":
            return ConnectionState.SYNC_FAILED.value, None, False
        if sync_status == "degraded":
            return ConnectionState.DEGRADED.value, None, False
        if not secret_configured:
            return ConnectionState.CREDENTIAL_WAITING.value, CONFIGURE_CREDENTIAL, True
        if not enabled:
            return ConnectionState.DISABLED.value, ENABLE_CONNECTION, True
        # enabled + credential configured + never synced (or disabled status).
        return ConnectionState.INITIAL_SYNC_PENDING.value, FIRST_SYNC, True

    # ── Connect actions (delegate to the shared connector_service) ───────────

    async def run_connect_action(
        self,
        tenant_id: str,
        family: str,
        action: str,
        *,
        name: Optional[str] = None,
        credential: Optional[str] = None,
        since: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run one activation connect action via connector_service.

        Returns the post-action connection state derived from the re-read
        tenant row. A failed initial sync returns an honest ``ok=False`` +
        ``sync_failed`` state rather than a server error; invalid family/action
        and consent-policy denials are client errors.
        """
        if action not in _CONNECT_ACTIONS:
            raise BadRequestError(f"unknown connect action: {action}")

        manifest = self._require_actionable_manifest(family)
        connector_type = manifest.provider_family

        try:
            if action == FIRST_SYNC:
                await connector_service.sync(
                    tenant_id, connector_type, actor_id="activation", since=since
                )
            else:
                await connector_service.configure(
                    tenant_id,
                    connector_type,
                    name=name or "",
                    enabled=True,
                    credential=credential,
                    actor_id="activation",
                )
        except ForbiddenError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface an honest failure
            logger.warning(
                f"activation connect action failed tenant={tenant_id} "
                f"family={family} action={action}: {exc}"
            )
            if action == FIRST_SYNC:
                return {
                    "family": family,
                    "action": action,
                    "ok": False,
                    "connection_state": ConnectionState.SYNC_FAILED.value,
                    "detail": str(exc)[:300],
                }
            raise BadRequestError(f"connect action {action} failed: {exc}") from exc

        row = await connector_service.get(tenant_id, connector_type)
        state, next_action, can_act = self._derive_from_facts(
            str((row or {}).get("sync_status") or "never_synced"),
            bool((row or {}).get("enabled")),
            bool((row or {}).get("secret_configured")),
        )
        return {
            "family": family,
            "action": action,
            "ok": True,
            "connection_state": state,
            "next_action": next_action,
            "can_act": can_act,
        }

    @staticmethod
    def _require_actionable_manifest(family: str) -> ProviderManifest:
        """A connectable (connector_service) manifest for ``family`` or 400."""
        from shared.integration_contracts.catalog import ALL_MANIFESTS

        candidates = [
            m
            for m in ALL_MANIFESTS
            if m.provider_family == family
            and m.product_id == "ingestion"
            and m.availability.tenant_self_service
            and m.availability.environments.any_enabled()
        ]
        if not candidates:
            raise BadRequestError(
                f"{family} is not a self-serve activation integration"
            )
        return candidates[0]


__all__ = [
    "ActivationPlanner",
    "CONFIGURE_CREDENTIAL",
    "CREATE_INTEGRATION",
    "ENABLE_CONNECTION",
    "FIRST_SYNC",
]
