"""Async SDK manifest publish requests through the Reconciled Control Plane.

The direct ``PUT /v1/config/sdk/manifest`` path is a legacy synchronous
publisher: it writes the active manifest immediately and owns its own
``rollout_percentage``. When the control plane is enabled that becomes a second
configuration authority, so a tenant instead *requests* the change here.

A request is deliberately not a publish. It records:

* a §32 ``ChangeSet`` plan for one ``remote_manifest_change`` with the requested
  manifest payload and the current manifest version as the observed revision;
* a §40 rollout record at stage zero (``olympus_internal``, 0%), linked to the
  ChangeSet and gated on ``gate:simulation``.

Nothing in this module applies the change or advances the rollout. The request
is accepted only when the effective activation decision grants ``plan``; an
``execute`` capability is *not* used here. The SDK-facing manifest is unchanged
until a later governed rollout/execution slice publishes it through
``SDKConfigService``.

Scope: ``SDKConfigService`` is tenant-wide, while RCP scopes are
tenant/environment. Requests therefore use the explicit tenant-wide environment
token :data:`SDK_CONFIG_ENVIRONMENT_ID` (``"all"``) rather than inventing a
real tenant environment.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Optional

from connectors.managed_integrations.activation import (
    RUNTIME_CAPABILITY_PLAN,
    RuntimeActivationDecision,
    RuntimeActivationResolver,
)
from connectors.managed_integrations.change_planning import build_requested_plan
from connectors.managed_integrations.change_sets_repository import (
    get_change_set_repository,
)
from connectors.managed_integrations.contracts import ChangeSpec
from connectors.managed_integrations.rollout_repository import (
    RolloutRecordRow,
    get_rollout_repository,
)

SDK_CONFIG_ENVIRONMENT_ID = "all"
SDK_CONFIG_INTEGRATION_REF_PREFIX = "sdk_config:"
SDK_CONFIG_REQUEST_POLICY_REF = "sdk_manifest_request:v1"
SDK_CONFIG_REQUEST_ADVANCE_CONDITION = "gate:simulation"
SDK_CONFIG_REQUEST_ENDPOINT = "/v1/config/sdk/manifest/requests"


class SDKManifestRequestRefused(Exception):
    """A request cannot be planned under the current activation authority."""

    def __init__(
        self,
        reason: str,
        *,
        state: str,
        blockers: tuple[str, ...] = (),
    ) -> None:
        self.reason = reason
        self.state = state
        self.blockers = blockers
        detail = f"{reason} (activation={state}"
        if blockers:
            detail += f", blockers={','.join(blockers)}"
        detail += ")"
        super().__init__(detail)


class SDKManifestRequestNotFound(Exception):
    """No request exists in the caller's tenant/environment scope."""


class SDKManifestRequestService:
    """Plan and record a requested SDK manifest change; never publish it."""

    def __init__(
        self,
        *,
        activation_resolver: Optional[RuntimeActivationResolver] = None,
        change_sets: Any = None,
        rollouts: Any = None,
        sdk_config: Any = None,
    ) -> None:
        self._activation = activation_resolver or RuntimeActivationResolver()
        self._change_sets = change_sets or get_change_set_repository()
        self._rollouts = rollouts or get_rollout_repository()
        self._sdk_config = sdk_config

    def _sdk_config_service(self) -> Any:
        if self._sdk_config is None:
            from ingestion.sdk_config.service import get_sdk_config_service

            self._sdk_config = get_sdk_config_service()
        return self._sdk_config

    async def request_manifest_change(
        self,
        *,
        tenant_id: str,
        initiator: str,
        min_sdk_version: str,
        schema_version: str,
        features: dict[str, bool],
        endpoints: dict[str, str],
        flags: dict[str, Any],
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record a planned ChangeSet + stage-zero rollout for the request."""
        decision = await self._activation.resolve(
            tenant_id=tenant_id,
            environment_id=SDK_CONFIG_ENVIRONMENT_ID,
        )
        if not decision.can(RUNTIME_CAPABILITY_PLAN):
            raise SDKManifestRequestRefused(
                "activation_insufficient",
                state=decision.state,
                blockers=decision.blockers,
            )

        manifest_payload = {
            "min_sdk_version": min_sdk_version,
            "schema_version": schema_version,
            "features": dict(features),
            "endpoints": dict(endpoints),
            "flags": dict(flags),
        }
        desired_revision = self._desired_revision(manifest_payload)
        changeset_id, rollout_id = self._request_ids(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )

        existing = await self._change_sets.get(
            tenant_id, SDK_CONFIG_ENVIRONMENT_ID, changeset_id
        )
        if existing is not None:
            if existing.get("desired_revision") != desired_revision:
                raise SDKManifestRequestRefused(
                    "idempotency_key_reused",
                    state=decision.state,
                    blockers=decision.blockers,
                )
            rollout = await self._rollouts.get(
                tenant_id=tenant_id,
                environment_id=SDK_CONFIG_ENVIRONMENT_ID,
                rollout_id=rollout_id,
            )
            if rollout is None:
                rollout = await self._create_rollout(
                    tenant_id=tenant_id,
                    changeset_id=changeset_id,
                    rollout_id=rollout_id,
                )
            return self._response(existing, rollout, decision)

        observed_revision = await self._observed_revision(tenant_id, decision)
        integration_ref = self._integration_ref(tenant_id)
        change = ChangeSpec(
            action="remote_manifest_change",
            target_ref=integration_ref,
            params={
                **manifest_payload,
                "tenant_id": tenant_id,
                "environment_id": SDK_CONFIG_ENVIRONMENT_ID,
                "request_id": changeset_id,
            },
            reason=reason or "tenant-requested SDK manifest update",
        )
        plan = build_requested_plan(
            managed_integration_ref=integration_ref,
            tenant_id=tenant_id,
            environment_id=SDK_CONFIG_ENVIRONMENT_ID,
            desired_revision=desired_revision,
            observed_revision=observed_revision,
            reconcile_sequence=f"sdkcfg_request:{changeset_id}",
            changes=[change],
            initiator=initiator,
            reason=reason or "tenant-requested SDK manifest update",
            integration_kind="sdk_web",
            policy_ref=SDK_CONFIG_REQUEST_POLICY_REF,
            changeset_id=changeset_id,
        )
        changeset = await self._change_sets.create(plan)
        rollout = await self._create_rollout(
            tenant_id=tenant_id,
            changeset_id=changeset_id,
            rollout_id=rollout_id,
        )
        return self._response(changeset, rollout, decision)

    async def get_request(self, *, tenant_id: str, request_id: str) -> dict[str, Any]:
        """Return the durable request (ChangeSet + rollout) for this tenant."""
        changeset = await self._change_sets.get(
            tenant_id, SDK_CONFIG_ENVIRONMENT_ID, request_id
        )
        if changeset is None:
            raise SDKManifestRequestNotFound(request_id)
        rollout_id = self._rollout_id_for(request_id)
        rollout = await self._rollouts.get(
            tenant_id=tenant_id,
            environment_id=SDK_CONFIG_ENVIRONMENT_ID,
            rollout_id=rollout_id,
        )
        return self._response(changeset, rollout, None)

    async def _create_rollout(
        self, *, tenant_id: str, changeset_id: str, rollout_id: str
    ) -> dict:
        row = RolloutRecordRow(
            rollout_id=rollout_id,
            changeset_ref=changeset_id,
            artifact_kind="runtime_config",
            strategy="canary",
            current_stage="olympus_internal",
            percentage=0.0,
            advance_conditions=[SDK_CONFIG_REQUEST_ADVANCE_CONDITION],
            tenant_id=tenant_id,
            environment_id=SDK_CONFIG_ENVIRONMENT_ID,
        )
        return await self._rollouts.create(row)

    async def _observed_revision(
        self, tenant_id: str, decision: RuntimeActivationDecision
    ) -> str:
        try:
            status = await self._sdk_config_service().get_rollout_status(tenant_id)
        except Exception as exc:
            raise SDKManifestRequestRefused(
                "observed_state_unavailable",
                state=decision.state,
                blockers=decision.blockers,
            ) from exc
        current = status.get("current_version") if isinstance(status, dict) else None
        return f"sdkcfg:{current or 'none'}"

    @staticmethod
    def _integration_ref(tenant_id: str) -> str:
        return f"{SDK_CONFIG_INTEGRATION_REF_PREFIX}{tenant_id}"

    @staticmethod
    def _desired_revision(manifest_payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            manifest_payload, sort_keys=True, separators=(",", ":"), default=str
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"sdkcfg_{digest[:20]}"

    @staticmethod
    def _request_ids(
        *,
        tenant_id: str,
        idempotency_key: Optional[str],
    ) -> tuple[str, str]:
        if idempotency_key and idempotency_key.strip():
            key = idempotency_key.strip()
        else:
            key = uuid.uuid4().hex
        digest = hashlib.sha256(
            f"{tenant_id}|{SDK_CONFIG_ENVIRONMENT_ID}|{key}".encode("utf-8")
        ).hexdigest()
        return f"rcs_sdk_{digest[:20]}", f"rcr_sdk_{digest[:20]}"

    @staticmethod
    def _rollout_id_for(changeset_id: str) -> str:
        if changeset_id.startswith("rcs_sdk_"):
            return "rcr_sdk_" + changeset_id[len("rcs_sdk_") :]
        digest = hashlib.sha256(changeset_id.encode("utf-8")).hexdigest()
        return f"rcr_sdk_{digest[:20]}"

    @staticmethod
    def _response(
        changeset: dict,
        rollout: Optional[dict],
        decision: Optional[RuntimeActivationDecision],
    ) -> dict[str, Any]:
        risk = changeset.get("risk") or {}
        return {
            "request_id": changeset.get("changeset_id"),
            "changeset_id": changeset.get("changeset_id"),
            "rollout_id": rollout.get("rollout_id") if rollout else None,
            "status": changeset.get("status"),
            "execution_state": "not_started",
            "manifest_published": False,
            "desired_revision": changeset.get("desired_revision"),
            "observed_revision": changeset.get("observed_revision"),
            "risk_class": risk.get("risk_class"),
            "automation_allowed": risk.get("automation_allowed"),
            "activation_state": decision.state if decision else None,
            "activation_capabilities": (
                sorted(decision.capabilities) if decision else []
            ),
            "rollout_stage": rollout.get("current_stage") if rollout else None,
            "rollout_percentage": rollout.get("percentage") if rollout else None,
            "note": (
                "Request recorded as a planned ChangeSet and stage-zero rollout; "
                "no SDK manifest has been published."
            ),
        }


_SERVICE: Optional[SDKManifestRequestService] = None


def get_sdk_manifest_request_service() -> SDKManifestRequestService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = SDKManifestRequestService()
    return _SERVICE


__all__ = [
    "SDK_CONFIG_ENVIRONMENT_ID",
    "SDK_CONFIG_REQUEST_ADVANCE_CONDITION",
    "SDK_CONFIG_REQUEST_ENDPOINT",
    "SDKManifestRequestNotFound",
    "SDKManifestRequestRefused",
    "SDKManifestRequestService",
    "get_sdk_manifest_request_service",
]
