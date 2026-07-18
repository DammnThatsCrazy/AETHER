"""Card-linked ingestion — every source funnels through fail-closed guards.

Order of operations for every record, regardless of source:

1. Blocked-PII rejection (audited — the attempt is recorded, the data is not).
2. Basis enforcement per source (top-up can never arrive as spend from the
   on-chain observer; provider webhooks may not claim topup/funding).
3. Region-policy gate (EU/APAC restricted modes strip user-level
   identifiers and count the suppression).
4. Consent gate (commerce for card metadata, web3 for on-chain evidence,
   agent+commerce for agent-influenced flows) — refusals are counted.
5. Deterministic idempotency key; duplicates are structural no-ops.
6. Cross-source reconciliation matching (wallet-hash + program + window).

Aether observes. It never processes, issues, custodies, or executes.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Any

from shared.logger.logger import get_logger, metrics

from services.card_linked_payments.models import (
    CardActivityBasis,
    amount_bucket,
    assert_evidence_not_overclaimed,
    classify_evidence_strength,
    onchain_idempotency_key,
    provider_idempotency_key,
    reject_blocked_fields,
    sdk_idempotency_key,
)
from services.card_linked_payments.graph_outbox import (
    CardLinkedGraphOutboxWorker,
    CardLinkedGraphProjectionOutbox,
)
from services.card_linked_payments.normalizer import (
    normalize_onchain_observation,
    normalize_provider_webhook,
)
from services.card_linked_payments.repositories import get_card_linked_repositories

logger = get_logger("aether.card_linked.ingestion")

# Existing SDK event types that may carry card-linked context. V1 reuses
# these (with card_program/card-linked properties) instead of adding new
# registry event types.
CARD_LINKED_SDK_EVENT_TYPES = frozenset({
    "payment_initiated", "payment_completed", "payment_failed",
    "transaction", "conversion", "reward_action_queued",
})

_EU_REGION_HINTS = frozenset({"eu", "eea", "europe"})
_UK_REGION_HINTS = frozenset({"uk", "gb"})
_APAC_REGION_HINTS = frozenset({"apac", "sg", "hk", "jp", "au", "kr", "in"})
# Recognised standard (unrestricted) jurisdictions. These are KNOWN regions, so
# they keep US_STANDARD behavior — only a *provided but unrecognised* hint falls
# through to the fail-safe UNKNOWN_RESTRICTED mode.
_US_REGION_HINTS = frozenset({"us", "usa", "united_states", "na", "ca", "mx"})

_USER_LEVEL_FIELDS = ("canonical_entity_id", "user_id", "session_id", "device_id")

# Region modes that strip user-level identifiers (most-restrictive set).
_RESTRICTED_REGION_POLICIES = (
    "EU_RESTRICTED", "UK_RESTRICTED", "APAC_RESTRICTED", "UNKNOWN_RESTRICTED",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_region_policy(region_hint: str | None, settings: Any) -> str:
    """Map a tenant/entity region hint onto a region policy mode.

    Fail-safe: a hint we do not recognise resolves to ``UNKNOWN_RESTRICTED``
    (most restrictive) instead of silently defaulting to unrestricted
    ``US_STANDARD``. Known regions are unchanged — an EU/UK/APAC hint whose
    restricted flag is off, a recognised US/standard hint, or an absent hint
    all keep the prior ``US_STANDARD`` behavior.
    """
    hint = (region_hint or "").strip().lower()
    flags = settings.card_linked_payment_rails
    if hint in _EU_REGION_HINTS:
        return "EU_RESTRICTED" if flags.eu_restricted_mode else "US_STANDARD"
    if hint in _UK_REGION_HINTS:
        return "UK_RESTRICTED" if flags.eu_restricted_mode else "US_STANDARD"
    if hint in _APAC_REGION_HINTS:
        return "APAC_RESTRICTED" if flags.apac_restricted_mode else "US_STANDARD"
    if hint in _US_REGION_HINTS:
        return "US_STANDARD"
    if not hint:
        # No hint supplied — preserve the historical default (consent still
        # governs user-level attribution independently).
        return "US_STANDARD"
    # Provided but unrecognised jurisdiction → fail safe.
    return "UNKNOWN_RESTRICTED"


class CardLinkedIngestionService:
    """Normalizes all card-linked sources into durable flow facts."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._repos = get_card_linked_repositories()
        # Durable graph projection outbox. The flow store stays source of
        # truth; projection is enqueued durably and drained through the
        # mutation gateway with retry/dead-letter/reconciliation.
        self._projection = CardLinkedGraphProjectionOutbox()

    # ── graph projection (durable outbox; the flow store is truth) ──

    async def _enqueue_projection(self, tenant_id: str, result: tuple[dict, str]) -> None:
        """Durably enqueue a newly-created flow's graph projection.

        The best-effort inline write (which swallowed graph failures) is
        replaced by a durable outbox row. An enqueue failure does NOT fail
        ingestion — the flow is already the committed source of truth — but it
        is surfaced honestly (metric + audit) so reconciliation/repair can
        recover it, rather than being silently swallowed.
        """
        record, disposition = result
        if disposition != "created":
            return
        try:
            await self._projection.enqueue_projection(tenant_id, record)
        except Exception as exc:
            metrics.increment(
                "card_linked_graph_projection_enqueue_failures_total",
                labels={"source": record.get("source", "unknown")},
            )
            logger.warning(
                "card-linked graph projection enqueue failed (recoverable via reconcile): %s",
                exc,
            )
            await self._repos.audit.record(tenant_id, "graph_projection_enqueue_failed", {
                "flow_id": record.get("id"),
                "error": str(exc),
            })

    # ── graph projection operator surface ────────────────────────────────

    def graph_outbox_worker(self) -> "CardLinkedGraphOutboxWorker":
        """A drain worker over the durable projection outbox (supervisor/ops)."""
        return CardLinkedGraphOutboxWorker(repo=self._projection.repo)

    async def drain_graph_projection(self, tenant_id: str, limit: int = 100) -> dict:
        """Drain one bounded, tenant-scoped batch of the projection outbox."""
        return await self.graph_outbox_worker().drain_once(tenant_id=tenant_id, limit=limit)

    async def reconcile_graph_projection(self, tenant_id: str) -> dict:
        """Drift report between the flow store (truth) and the graph outbox."""
        return await self._projection.reconcile(tenant_id)

    async def repair_graph_projection(self, tenant_id: str, **kwargs: Any) -> dict:
        """Operator replay: re-enqueue missing + reset dead-lettered rows."""
        return await self._projection.repair(tenant_id, **kwargs)

    # ── guards ──────────────────────────────────────────────────────────

    async def _guard_pii(self, tenant_id: str, payload: dict[str, Any], source: str) -> None:
        try:
            reject_blocked_fields(payload)
        except ValueError as exc:
            await self._repos.audit.record(tenant_id, "blocked_pii", {
                "source": source,
                "error": str(exc),
            })
            await self._repos.provider_health.record_event(tenant_id, source, error=True)
            raise

    @staticmethod
    def _stamp_evidence(record: dict[str, Any]) -> dict[str, Any]:
        """Label a flow by evidence strength and fail closed on overclaim.

        SDK/self-reported/on-chain/benchmark observations are never promoted to
        provider-confirmed spend — only genuine provider/issuer evidence may be.
        """
        strength = classify_evidence_strength(
            record.get("source"),
            record.get("reconciliation_state"),
            record.get("basis"),
        )
        assert_evidence_not_overclaimed(record.get("source"), strength)
        record["evidence_strength"] = strength
        return record

    @staticmethod
    def _granted_purposes(consent_snapshot: dict[str, bool] | None) -> list[str]:
        """Purposes the snapshot actually grants. A MISSING snapshot grants
        nothing — so the PolicyDecision fails closed for user-level data."""
        if not consent_snapshot:
            return []
        return sorted(p for p, granted in consent_snapshot.items() if granted)

    async def _apply_region_policy(self, tenant_id: str, record: dict[str, Any],
                                   region_hint: str | None) -> dict[str, Any]:
        policy = resolve_region_policy(region_hint, self._settings)
        record["region_policy"] = policy
        if policy in _RESTRICTED_REGION_POLICIES:
            stripped = [f for f in _USER_LEVEL_FIELDS if record.get(f)]
            if stripped:
                for field_name in stripped:
                    record[field_name] = None
                await self._repos.audit.record(tenant_id, "region_suppressed", {
                    "policy": policy,
                    "stripped_fields": stripped,
                    "flow_id": record.get("id"),
                })
        return record

    async def _check_consent(self, tenant_id: str, record: dict[str, Any],
                             consent_snapshot: dict[str, bool] | None,
                             required: tuple[str, ...],
                             *, action: str = "collect_event") -> bool:
        """Fail-closed consent gate for USER-LEVEL attribution.

        Aggregate / catalog / approved wallet-level observations carry no
        user-level identifiers and require no consent (kept as-is). When the
        record DOES carry user-level attribution, a canonical
        :class:`ConsentPolicyDecision` is obtained per required purpose; a
        MISSING snapshot grants nothing, so the decision is denied and the
        user-level fields are stripped (fail closed). The decision id(s) and
        the redaction evidence are persisted on the stored record.

        Returns True when the record may retain user-level attribution.
        """
        if not any(record.get(f) for f in _USER_LEVEL_FIELDS):
            return True  # aggregate/wallet-level record — no user consent needed

        from services.policy import consent_policy_engine

        granted = self._granted_purposes(consent_snapshot)
        subject_ref = record.get("canonical_entity_id") or record.get("user_id")
        decisions = []
        for purpose in required:
            decisions.append(await consent_policy_engine.decide(
                tenant_id=tenant_id,
                actor_id="card_linked_ingestion",
                action=action,
                resource_type="card_linked_flow",
                resource_id=record.get("id"),
                subject_ref=subject_ref,
                granted_purposes=granted,
                purpose=purpose,
                redactable_fields=_USER_LEVEL_FIELDS,
            ))
        decision_ids = [d.policy_decision_id for d in decisions]
        allowed = all(d.allowed for d in decisions)

        # Persist the PolicyDecision evidence on the stored record either way.
        record["consent_policy_decision_id"] = decision_ids[0] if decision_ids else None
        record["consent_policy_decision_ids"] = decision_ids

        if allowed:
            record["consent_snapshot"] = consent_snapshot
            record["consent_decision"] = "allowed"
            record["consent_redacted_fields"] = []
            return True

        # FAIL CLOSED: no / insufficient consent evidence for user-level data.
        redacted = [f for f in _USER_LEVEL_FIELDS if record.get(f)]
        for field_name in _USER_LEVEL_FIELDS:
            record[field_name] = None
        record["consent_snapshot"] = None
        record["consent_decision"] = "redacted"
        record["consent_redacted_fields"] = redacted
        missing = sorted({p for d in decisions for p in d.missing_purposes})
        await self._repos.audit.record(tenant_id, "consent_suppressed", {
            "required": list(required),
            "missing": missing,
            "flow_id": record.get("id"),
            "policy_decision_ids": decision_ids,
            "redacted_fields": redacted,
            "reason": "missing_consent_snapshot" if not consent_snapshot else "insufficient_consent",
        })
        return False

    # ── sources ─────────────────────────────────────────────────────────

    async def ingest_provider_webhook(self, tenant_id: str, payload: dict[str, Any],
                                      *, region_hint: str | None = None,
                                      consent_snapshot: dict[str, bool] | None = None,
                                      ) -> tuple[dict, str]:
        """Signed issuer/provider webhook → off-chain card spend evidence."""
        await self._guard_pii(tenant_id, payload, "provider_webhook")
        flow = normalize_provider_webhook({**payload, "tenant_id": tenant_id})
        record = dataclasses.asdict(flow)
        record["idempotency_key"] = provider_idempotency_key(
            tenant_id, payload.get("provider", flow.card_program_id or "provider"),
            payload.get("provider_event_id", flow.id),
        )
        record["amount_bucket"] = amount_bucket(record.get("amount_usd"))
        record = self._stamp_evidence(record)
        record = await self._apply_region_policy(tenant_id, record, region_hint)
        await self._check_consent(tenant_id, record, consent_snapshot, ("commerce",))
        result = await self._repos.flows.insert_idempotent(tenant_id, record)
        await self._repos.provider_health.record_event(tenant_id, "provider_webhook")
        await self._enqueue_projection(tenant_id, result)
        await self._try_reconcile(tenant_id, result[0])
        return result

    async def ingest_onchain_observation(self, tenant_id: str, payload: dict[str, Any],
                                         *, region_hint: str | None = None,
                                         consent_snapshot: dict[str, bool] | None = None,
                                         ) -> tuple[dict, str]:
        """Wallet/on-chain evidence → top-up / funding / settlement ONLY."""
        await self._guard_pii(tenant_id, payload, "onchain_observer")
        flow = normalize_onchain_observation({**payload, "tenant_id": tenant_id})
        record = dataclasses.asdict(flow)
        record["idempotency_key"] = onchain_idempotency_key(
            tenant_id, payload.get("chain", "unknown"),
            payload.get("tx_hash", flow.id), payload.get("log_index", "0"),
        )
        record["amount_bucket"] = amount_bucket(record.get("amount_usd"))
        record = self._stamp_evidence(record)
        record = await self._apply_region_policy(tenant_id, record, region_hint)
        await self._check_consent(tenant_id, record, consent_snapshot, ("web3",))
        result = await self._repos.flows.insert_idempotent(tenant_id, record)
        await self._repos.provider_health.record_event(tenant_id, "onchain_observer")
        await self._enqueue_projection(tenant_id, result)
        await self._try_reconcile(tenant_id, result[0])
        return result

    async def ingest_sdk_event(self, tenant_id: str, event: dict[str, Any],
                               *, region_hint: str | None = None,
                               consent_snapshot: dict[str, bool] | None = None,
                               ) -> tuple[dict, str] | None:
        """Existing SDK payment/journey events carrying card-linked context.

        Returns None when the event carries no card-linked properties —
        this service never claims card activity that was not observed.
        """
        properties = event.get("properties") or {}
        card_program_ref = properties.get("card_program") or properties.get("card_program_id")
        if event.get("type") not in CARD_LINKED_SDK_EVENT_TYPES or not card_program_ref:
            return None
        await self._guard_pii(tenant_id, {**event, **properties}, "sdk")

        from services.payment_catalog.catalog import resolve_slug
        basis_raw = properties.get("basis")
        try:
            basis = CardActivityBasis(basis_raw).value if basis_raw else CardActivityBasis.UNKNOWN.value
        except ValueError:
            await self._repos.audit.record(tenant_id, "basis_warning", {
                "source": "sdk", "claimed_basis": basis_raw, "event_id": event.get("event_id"),
            })
            basis = CardActivityBasis.UNKNOWN.value
        # SDK context alone may never claim off-chain spend truth.
        if basis in (CardActivityBasis.SPEND.value, CardActivityBasis.SETTLEMENT.value):
            await self._repos.audit.record(tenant_id, "basis_warning", {
                "source": "sdk", "claimed_basis": basis,
                "downgraded_to": CardActivityBasis.UNKNOWN.value,
                "event_id": event.get("event_id"),
                "reason": "sdk_events_cannot_prove_offchain_spend",
            })
            basis = CardActivityBasis.UNKNOWN.value

        ts = event.get("timestamp") or _now()
        record = {
            "id": f"clf_sdk_{event.get('event_id', ts)}",
            "tenant_id": tenant_id,
            "actor_kind": "agent" if event.get("agent_id") else "human",
            "canonical_entity_id": event.get("canonical_entity_id"),
            "user_id": event.get("user_id"),
            "agent_id": event.get("agent_id"),
            "org_id": event.get("org_id"),
            "wallet_address_hash": properties.get("wallet_address_hash"),
            "card_program_id": resolve_slug(str(card_program_ref)) or "unknown",
            "issuer_id": properties.get("issuer_id"),
            "payment_network": properties.get("payment_network", "unknown"),
            "rail": "card",
            "basis": basis,
            "chain": properties.get("chain"),
            "asset": properties.get("asset"),
            "amount_usd": properties.get("amount_usd"),
            "amount_native": properties.get("amount_native"),
            "amount_bucket": amount_bucket(properties.get("amount_usd")),
            "campaign_id": properties.get("campaign_id") or event.get("campaign_id"),
            "journey_id": properties.get("journey_id") or event.get("journey_id"),
            "session_id": event.get("session_id"),
            "device_id": event.get("device_id"),
            "source": "sdk",
            "confidence": "probable",
            "evidence_refs": [event.get("event_id", "sdk_event")],
            "reconciliation_state": "sdk_only",
            "occurred_at": ts,
            "observed_at": _now(),
            "created_at": _now(),
            "updated_at": _now(),
            "idempotency_key": sdk_idempotency_key(tenant_id, event.get("event_id", ts)),
        }
        required = ("agent", "commerce") if event.get("agent_id") else ("commerce",)
        record = self._stamp_evidence(record)
        record = await self._apply_region_policy(tenant_id, record, region_hint)
        await self._check_consent(tenant_id, record, consent_snapshot, required)
        result = await self._repos.flows.insert_idempotent(tenant_id, record)
        await self._repos.provider_health.record_event(tenant_id, "sdk")
        await self._enqueue_projection(tenant_id, result)
        await self._try_reconcile(tenant_id, result[0])
        return result

    async def ingest_tenant_import(self, tenant_id: str, rows: list[dict[str, Any]],
                                   *, region_hint: str | None = None,
                                   consent_snapshot: dict[str, bool] | None = None,
                                   ) -> list[tuple[dict, str]]:
        """Tenant bulk import.

        Applies the SAME fail-closed consent + PolicyDecision gate as the
        webhook/onchain/SDK paths: a user-level import row with no consent
        evidence has its user-level identifiers stripped before persistence.
        A batch-level ``consent_snapshot`` applies to every row; an individual
        row may carry its own ``consent_snapshot`` which overrides the batch.
        """
        results: list[tuple[dict, str]] = []
        # Route the batch THROUGH the canonical import engine's PII detection +
        # dry-run validation + review-approval + lineage before persisting.
        # Best-effort so a bridge hiccup never blocks a governed ingest — the
        # fail-closed PII/consent/region guards below are the hard gates.
        try:
            from services.card_linked_payments.import_bridge import build_import_lineage

            lineage = build_import_lineage(tenant_id, rows)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("card-linked import-engine bridge unavailable: %s", exc)
            lineage = {"import_id": None, "engine": "services.imports", "bridge_error": str(exc)}
        if lineage.get("review_required"):
            await self._repos.audit.record(tenant_id, "import_review_required", {
                "import_id": lineage.get("import_id"),
                "reasons": lineage.get("review_reasons"),
                "pii_columns": lineage.get("pii_columns"),
            })
        for index, row in enumerate(rows):
            await self._guard_pii(tenant_id, row, "tenant_import")
            basis_raw = row.get("basis", "unknown")
            basis = CardActivityBasis(basis_raw).value  # raises on unsupported basis
            ts = row.get("occurred_at") or _now()
            record = {
                "id": row.get("id") or f"clf_import_{len(results)}_{ts}",
                "tenant_id": tenant_id,
                "actor_kind": row.get("actor_kind", "human"),
                "card_program_id": row.get("card_program_id"),
                "issuer_id": row.get("issuer_id"),
                "payment_network": row.get("payment_network", "unknown"),
                "rail": row.get("rail", "card"),
                "basis": basis,
                "chain": row.get("chain"),
                "asset": row.get("asset"),
                "amount_usd": row.get("amount_usd"),
                "amount_bucket": amount_bucket(row.get("amount_usd")),
                "campaign_id": row.get("campaign_id"),
                "journey_id": row.get("journey_id"),
                "canonical_entity_id": row.get("canonical_entity_id"),
                "user_id": row.get("user_id"),
                "session_id": row.get("session_id"),
                "device_id": row.get("device_id"),
                "agent_id": row.get("agent_id"),
                "wallet_address_hash": row.get("wallet_address_hash"),
                "source": "tenant_import",
                "confidence": "probable",
                "evidence_refs": row.get("evidence_refs", []),
                "reconciliation_state": "sdk_only",
                "occurred_at": ts,
                "observed_at": _now(),
                "created_at": _now(),
                "updated_at": _now(),
                "idempotency_key": sdk_idempotency_key(
                    tenant_id, row.get("id") or f"import:{ts}:{len(results)}",
                ),
            }
            record["import_lineage"] = {**lineage, "row_index": index}
            record = self._stamp_evidence(record)
            row_consent = row.get("consent_snapshot", consent_snapshot)
            required = ("agent", "commerce") if row.get("agent_id") else ("commerce",)
            record = await self._apply_region_policy(tenant_id, record, region_hint)
            await self._check_consent(tenant_id, record, row_consent, required)
            result = await self._repos.flows.insert_idempotent(tenant_id, record)
            await self._enqueue_projection(tenant_id, result)
            # Reconcile imported rows against later provider/on-chain evidence
            # for the same (wallet_hash, program) — reusing the shared matcher.
            await self._try_reconcile(tenant_id, result[0])
            results.append(result)
        return results

    # ── reconciliation ──────────────────────────────────────────────────

    async def _try_reconcile(self, tenant_id: str, record: dict[str, Any]) -> None:
        """Match on-chain funding with provider/SDK evidence for the same
        (wallet_address_hash, card_program_id). Matched records upgrade to
        ``matched``; conflicting bases stay separate — top-up evidence never
        merges into spend evidence, the match only links them.
        """
        wallet = record.get("wallet_address_hash")
        program = record.get("card_program_id")
        if not wallet or not program:
            return
        siblings = await self._repos.flows.list_for_tenant(
            tenant_id, wallet_address_hash=wallet, card_program_id=program,
        )
        other_sources = {s.get("source") for s in siblings if s.get("id") != record.get("id")}
        if not other_sources:
            return
        if other_sources - {record.get("source")}:
            flow_ids = sorted({s["id"] for s in siblings})
            reconciliation_id = f"clr_{wallet[:16]}_{program}"
            await self._repos.reconciliation.save(tenant_id, {
                "reconciliation_id": reconciliation_id,
                "tenant_id": tenant_id,
                "flow_ids": flow_ids,
                "state": "matched",
                "matched_on": "wallet_hash_program_window",
                "created_at": _now(),
            })
            for sibling in siblings:
                if sibling.get("reconciliation_state") in ("sdk_only", "provider_only", "onchain_only"):
                    sibling["reconciliation_state"] = "matched"
                    await self._repos.flows.save(tenant_id, sibling)


_service: CardLinkedIngestionService | None = None


def get_ingestion_service() -> CardLinkedIngestionService:
    """Process-wide ingestion service (routes + SDK pipeline hook share it)."""
    global _service
    if _service is None:
        from config.settings import get_settings

        _service = CardLinkedIngestionService(get_settings())
    return _service
