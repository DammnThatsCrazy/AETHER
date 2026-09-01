"""Self-serve activation service.

Orchestrates the tenant-driven activation flow by *reusing* existing
primitives — it does not reimplement them:

* API-key minting reuses the exact registration sequence
  (:class:`repositories.repos.APIKeyRepository` insert of a hashed key +
  ``registry.api_key_validator.register_api_key``).
* The test event is sent IN-PROCESS through the canonical
  :func:`services.ingestion.batch.ingest_batch`, so Bronze durability, the
  ``sha256(tenant_id:event_id:schema_version)`` idempotency claim, and the
  accepted/duplicate/rejected disposition are all the real ingestion path.
* First value is proved by reading the durable Bronze ``sdk_events`` rows —
  never a hard-coded success.
* Billing state is DERIVED read-only from the Stripe billing account; this
  service performs no billing writes.

State transitions go through :meth:`ActivationService.advance`, which enforces
an explicit ``ALLOWED_FROM`` map and raises :class:`ConflictError` on any
illegal transition. The ``manual_pending`` / ``blocked`` / ``externally_blocked``
states are set only when a precondition genuinely cannot be met — never faked
into a forward state.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any, Optional

from fastapi import Request

from shared.common.common import ConflictError, utc_now
from shared.billing import stripe_repository
from shared.logger.logger import get_logger, metrics
from shared.rights_authority.pep import rights_mode
from shared.rights_authority.service import rights_authority
from repositories.lake import BronzeRepository
from repositories.repos import APIKeyRepository
from dependencies.providers import get_producer, get_registry
from services.ingestion.batch import BaseEvent, BatchRequest, ingest_batch

from .models import ActivationRecord, ActivationState, TestEventRequest
from .repository import ActivationRepository

logger = get_logger("aether.service.activation")

S = ActivationState

# Stripe subscription statuses that mean billing is genuinely active. Everything
# else (incomplete, past_due, canceled, unpaid, paused, None) is treated as
# pending — the state is derived, never asserted.
_ACTIVE_SUBSCRIPTION_STATUSES: frozenset[str] = frozenset({"active", "trialing"})

# Key-minting posture reused verbatim from services/registration/routes.py.
_KEY_PERMISSIONS: list[str] = ["read", "write", "ingest", "analytics"]

# States the service may set from anywhere to record an honest inability to
# proceed. They are never a substitute for a forward state.
_HONEST_HALT_STATES: frozenset[ActivationState] = frozenset(
    {S.manual_pending, S.blocked, S.externally_blocked}
)

_ALL_STATES: frozenset[ActivationState] = frozenset(ActivationState)


class ActivationService:
    """Drives the self-serve activation lifecycle for a tenant."""

    # target_state -> set of states it may legally be entered from. A
    # self-transition (current == target) is always permitted for idempotent
    # re-calls; the honest-halt states may be entered from anywhere.
    ALLOWED_FROM: dict[ActivationState, frozenset[ActivationState]] = {
        S.account_verified: frozenset({S.not_started}),
        S.plan_selected: frozenset(
            {S.not_started, S.account_verified, S.billing_pending, S.billing_active}
        ),
        S.billing_pending: frozenset({S.plan_selected, S.billing_active}),
        S.billing_active: frozenset({S.plan_selected, S.billing_pending}),
        S.sdk_selected: frozenset(
            {S.plan_selected, S.billing_pending, S.billing_active}
        ),
        S.keys_created: frozenset({S.sdk_selected, S.waiting_for_event}),
        S.waiting_for_event: frozenset({S.keys_created, S.event_received}),
        S.event_received: frozenset({S.keys_created, S.waiting_for_event}),
        S.first_value_ready: frozenset({S.event_received, S.waiting_for_event}),
        S.complete: frozenset({S.first_value_ready}),
        S.manual_pending: _ALL_STATES,
        S.blocked: _ALL_STATES,
        S.externally_blocked: _ALL_STATES,
    }

    def __init__(self) -> None:
        self.repo = ActivationRepository()

    # ── State machine ────────────────────────────────────────────────────────

    def advance(
        self,
        record: dict[str, Any],
        target: ActivationState,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Move ``record`` to ``target`` or raise :class:`ConflictError`.

        A no-op self-transition still stamps ``updated_at`` but records no new
        history entry.
        """
        current = ActivationState(record.get("state", S.not_started.value))
        if current != target:
            allowed = self.ALLOWED_FROM.get(target, frozenset())
            if current not in allowed:
                raise ConflictError(
                    f"Illegal activation transition: {current.value} -> {target.value}"
                )
            record.setdefault("history", []).append({
                "from": current.value,
                "to": target.value,
                "at": utc_now().isoformat(),
                "reason": reason,
            })
            record["state"] = target.value
            metrics.increment(
                "activation_transition_total",
                labels={"to": target.value},
            )
        record["updated_at"] = utc_now().isoformat()
        return record

    # ── Record lifecycle ─────────────────────────────────────────────────────

    def _new_record(self, tenant_id: str) -> dict[str, Any]:
        now = utc_now().isoformat()
        return ActivationRecord(
            activation_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            state=S.not_started,
            created_at=now,
            updated_at=now,
        ).model_dump()

    async def _load_or_create(self, tenant_id: str) -> dict[str, Any]:
        record = await self.repo.get_for_tenant(tenant_id)
        if record is not None:
            return record
        record = self._new_record(tenant_id)
        # The caller is an authenticated tenant, so the account is verified.
        self.advance(record, S.account_verified, reason="tenant_authenticated")
        return await self.repo.save_or_update(record)

    async def _status_view(self, record: dict[str, Any]) -> dict[str, Any]:
        billing = await self.derive_billing_state(record["tenant_id"])
        rights = await self._rights_activation(record["tenant_id"])
        return {
            "state": record["state"],
            "selected_plan_tier": record.get("selected_plan_tier"),
            "sdk_selection": record.get("sdk_selection", []),
            "created_key_ids": record.get("created_key_ids", []),
            "billing_state": billing.value,
            "first_value_evidence": record.get("first_value_evidence", {}),
            "waiting_reason": record.get("waiting_reason"),
            "history": record.get("history", []),
            "rights": rights,
        }

    async def _rights_activation(self, tenant_id: str) -> dict[str, Any]:
        """Resolve the policy state used by activation without trusting cache."""
        if rights_mode() == "off":
            return {"mode": "off", "state": "not_enforced"}
        policies = await rights_authority.repository.list_policies(tenant_id)
        active = [
            policy for policy in policies
            if policy.get("activation_state") in {"rights_active", "rights_restricted"}
        ]
        if len(active) != 1:
            return {
                "mode": rights_mode(),
                "state": "blocked",
                "reason": "rights_policy_missing_or_ambiguous",
            }
        policy = active[0]
        return {
            "mode": rights_mode(),
            "state": policy.get("activation_state"),
            "policy_set_ref": policy.get("policy_set_id"),
        }

    # ── Billing (read-only derivation) ───────────────────────────────────────

    async def derive_billing_state(self, tenant_id: str) -> ActivationState:
        """Map the Stripe subscription status to a billing activation state.

        READ-ONLY: reads the billing account row and derives the state. It never
        writes billing data — a Stripe subscription is created through the
        billing service, not here.
        """
        account = await stripe_repository.get_billing_account(tenant_id)
        status = (account or {}).get("subscription_status")
        if status in _ACTIVE_SUBSCRIPTION_STATUSES:
            return S.billing_active
        return S.billing_pending

    # ── Public flow methods ──────────────────────────────────────────────────

    async def get_status(self, tenant_id: str) -> dict[str, Any]:
        record = await self._load_or_create(tenant_id)
        return await self._status_view(record)

    async def select_plan(self, tenant_id: str, plan_tier: str) -> dict[str, Any]:
        record = await self._load_or_create(tenant_id)
        self.advance(record, S.plan_selected, reason=f"plan_tier={plan_tier}")
        record["selected_plan_tier"] = plan_tier
        billing = await self.derive_billing_state(tenant_id)
        self.advance(record, billing, reason="billing_state_derived")
        record = await self.repo.save_or_update(record)
        return await self._status_view(record)

    async def select_sdks(self, tenant_id: str, platforms: list[str]) -> dict[str, Any]:
        record = await self._load_or_create(tenant_id)
        self.advance(record, S.sdk_selected, reason=f"platforms={list(platforms)}")
        record["sdk_selection"] = list(platforms)
        record = await self.repo.save_or_update(record)
        return await self._status_view(record)

    async def create_sdk_keys(
        self, tenant_id: str, count: int, label: str
    ) -> dict[str, Any]:
        record = await self._load_or_create(tenant_id)
        rights = await self._rights_activation(tenant_id)
        if rights.get("state") == "blocked":
            record["rights_blocked_reason"] = rights.get("reason")
            await self.repo.save_or_update(record)
            raise ConflictError("activation is blocked until an active rights policy is available")
        record["rights_policy_set_ref"] = rights.get("policy_set_ref")
        record["rights_activation_state"] = rights.get("state")
        self.advance(record, S.keys_created, reason=f"count={count}")
        tier = record.get("selected_plan_tier") or "P1"
        keys = await self.provision_sdk_keys(tenant_id, count, label, tier=tier)
        record["created_key_ids"] = list(record.get("created_key_ids", [])) + [
            k["id"] for k in keys
        ]
        # Keys exist; the tenant now needs to send a first event.
        self.advance(record, S.waiting_for_event, reason="keys_provisioned")
        record["waiting_reason"] = "no_events_received_yet"
        record = await self.repo.save_or_update(record)
        return {"keys": keys, "state": record["state"]}

    async def provision_sdk_keys(
        self, tenant_id: str, count: int, label: str, tier: str = "P1"
    ) -> list[dict[str, str]]:
        """Mint ``count`` API keys, reusing the registration key-mint sequence.

        Raw keys are returned exactly ONCE; only the hashed key id (``hashed[:12]``)
        is persisted here for the caller to record. The hashed key itself lives
        in the ``api_keys`` store, identical to public registration.
        """
        count = max(1, min(int(count), 5))
        registry = get_registry()
        key_repo = APIKeyRepository()
        minted: list[dict[str, str]] = []
        key_label = label or "onboarding key"
        for _ in range(count):
            raw_key = f"ak_{uuid.uuid4().hex[:24]}"
            hashed = hashlib.sha256(raw_key.encode()).hexdigest()
            key_id = hashed[:12]
            await key_repo.insert(key_id, {
                "tenant_id": tenant_id,
                "name": key_label,
                "tier": tier,
                "permissions": list(_KEY_PERMISSIONS),
                "key_hash": hashed,
                "last_used_at": None,
            })
            try:
                await registry.api_key_validator.register_api_key(
                    api_key=raw_key,
                    tenant_id=tenant_id,
                    role="editor",
                    tier=tier,
                    permissions=list(_KEY_PERMISSIONS),
                )
            except Exception as exc:
                logger.warning(
                    f"Auth cache registration failed: tenant={tenant_id} error={exc}"
                )
            minted.append({"id": key_id, "key": raw_key, "label": key_label})
        metrics.increment(
            "activation_sdk_keys_created_total",
            value=len(minted),
            labels={"tenant_id": tenant_id},
        )
        return minted

    async def run_test_event(
        self, request: Request, tenant_id: str, body: TestEventRequest
    ) -> dict[str, Any]:
        """Send a single event IN-PROCESS through the canonical ingestion path.

        Builds a real :class:`BatchRequest` and awaits
        :func:`services.ingestion.batch.ingest_batch` with the same request (so
        ``request.state.tenant`` authorizes it) — not an HTTP round-trip. The
        Bronze write, idempotency claim, and per-event disposition are the real
        ingestion behavior.
        """
        now = utc_now().isoformat()
        event = BaseEvent(
            id=str(uuid.uuid4()),
            type=body.event_type,
            timestamp=now,
            sessionId=body.session_id or str(uuid.uuid4()),
            anonymousId=body.anonymous_id or str(uuid.uuid4()),
            properties=body.properties or {},
        )
        batch_request = BatchRequest(batch=[event], sentAt=now)
        response = await ingest_batch(request, batch_request, get_producer())

        results: list[dict[str, Any]] = []
        for ev in response.get("events", []):
            result: dict[str, Any] = {"status": ev.get("status")}
            if ev.get("reason"):
                result["reason"] = ev["reason"]
            results.append(result)

        record = await self._load_or_create(tenant_id)
        record = await self._reconcile_first_value(record)
        record = await self.repo.save_or_update(record)
        return {"results": results, "state": record["state"]}

    async def evaluate_first_value(self, tenant_id: str) -> dict[str, Any]:
        record = await self._load_or_create(tenant_id)
        record = await self._reconcile_first_value(record)
        record = await self.repo.save_or_update(record)
        ready = record["state"] == S.first_value_ready.value
        return {
            "state": record["state"],
            "ready": ready,
            "evidence": record.get("first_value_evidence", {}),
        }

    async def complete(self, tenant_id: str) -> dict[str, Any]:
        record = await self._load_or_create(tenant_id)
        if record["state"] == S.complete.value:
            return await self._status_view(record)
        # Re-prove first value from durable evidence before allowing completion.
        record = await self._reconcile_first_value(record)
        if record["state"] != S.first_value_ready.value:
            raise ConflictError(
                "Activation cannot complete before first_value_ready "
                f"(current state: {record['state']})"
            )
        self.advance(record, S.complete, reason="tenant_completed")
        record = await self.repo.save_or_update(record)
        return await self._status_view(record)

    # ── First-value evidence (durable Bronze read) ───────────────────────────

    async def _reconcile_first_value(self, record: dict[str, Any]) -> dict[str, Any]:
        """Derive first-value state from the durable Bronze ``sdk_events`` rows.

        No rows  -> waiting_for_event (nothing has arrived yet).
        >=1 row  -> event_received then first_value_ready, with REAL
                    event_id / batch_id / received_at stored in the evidence
                    dict. The durable Bronze row IS the confirmation — there is
                    no hard-coded success.

        State is only moved when the record is at a point in the flow that can
        legally reach first value (keys created onward); an early record with a
        stray row is left untouched rather than force-transitioned.
        """
        tenant_id = record["tenant_id"]
        current = ActivationState(record["state"])
        reachable = {S.keys_created, S.waiting_for_event, S.event_received, S.first_value_ready}
        if current not in reachable:
            return record

        bronze = BronzeRepository("sdk_events")
        rows = await bronze.find_many(
            filters={"tenant_id": tenant_id, "source": "sdk"},
            limit=1,
            sort_by="created_at",
            sort_order="desc",
        )
        if not rows:
            if current == S.keys_created:
                self.advance(record, S.waiting_for_event, reason="no_bronze_rows")
            record["waiting_reason"] = "no_events_received_yet"
            return record

        row = rows[0]
        payload = row.get("payload") or {}
        event_id = row.get("provider_record_id") or payload.get("event_id")
        source_tag = row.get("source_tag") or ""
        if "batch:" in source_tag:
            batch_id = source_tag.split("batch:")[-1]
        else:
            batch_id = payload.get("batch_id")
        received_at = row.get("ingested_at") or payload.get("received_at")

        record["first_event_id"] = event_id
        record["first_event_batch_id"] = batch_id
        record["first_value_evidence"] = {
            "event_id": event_id,
            "batch_id": batch_id,
            "received_at": received_at,
            "source": "bronze_sdk_events",
            "bronze_id": row.get("id"),
            "confirmed": True,
        }
        record["waiting_reason"] = None

        if current not in {S.first_value_ready, S.complete}:
            self.advance(record, S.event_received, reason="bronze_row_present")
            self.advance(
                record, S.first_value_ready, reason="durable_bronze_row_confirmed"
            )
        return record
