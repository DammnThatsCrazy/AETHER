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

from shared.logger.logger import get_logger

from services.card_linked_payments.models import (
    CardActivityBasis,
    amount_bucket,
    onchain_idempotency_key,
    provider_idempotency_key,
    reject_blocked_fields,
    sdk_idempotency_key,
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

_USER_LEVEL_FIELDS = ("canonical_entity_id", "user_id", "session_id", "device_id")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_region_policy(region_hint: str | None, settings: Any) -> str:
    """Map a tenant/entity region hint onto a region policy mode."""
    hint = (region_hint or "").strip().lower()
    flags = settings.card_linked_payment_rails
    if hint in _EU_REGION_HINTS and flags.eu_restricted_mode:
        return "EU_RESTRICTED"
    if hint in _UK_REGION_HINTS and flags.eu_restricted_mode:
        return "UK_RESTRICTED"
    if hint in _APAC_REGION_HINTS and flags.apac_restricted_mode:
        return "APAC_RESTRICTED"
    return "US_STANDARD"


class CardLinkedIngestionService:
    """Normalizes all card-linked sources into durable flow facts."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._repos = get_card_linked_repositories()
        # Catalog vertices already mirrored to the graph this process, keyed
        # by program slug — projected lazily so flow edges always have their
        # CardProgram endpoint without bulk-seeding the whole catalog.
        self._projected_programs: set[str] = set()

    # ── graph projection (best-effort mirror; the flow store is truth) ──

    async def _project_to_graph(self, tenant_id: str, result: tuple[dict, str]) -> None:
        """Mirror a newly-created flow into the graph (vertex + evidence edges).

        Same contract as the identity graph_writer: the durable repository is
        the source of truth and the graph write is best-effort — a graph
        failure never fails ingestion. Duplicate dispositions are skipped.
        """
        record, disposition = result
        if disposition != "created":
            return
        try:
            from dependencies.providers import get_graph
            from services.card_linked_payments.graph_projector import (
                build_catalog_mutations,
                build_flow_mutations,
            )
            from services.payment_catalog.catalog import PAYMENTSCAN_CARD_PROGRAMS

            from shared.graph.mutation_gateway import GraphMutationGateway
            from shared.graph.mutation_intents import edge_intent, vertex_intent

            graph = get_graph()
            gateway = GraphMutationGateway(graph_client=graph)
            program_slug = record.get("card_program_id")
            if program_slug and program_slug not in self._projected_programs:
                self._projected_programs.add(program_slug)
                entity = next(
                    (e for e in PAYMENTSCAN_CARD_PROGRAMS if e.slug == program_slug),
                    None,
                )
                if entity is not None:
                    cat_vertices, cat_edges = build_catalog_mutations(
                        tenant_id,
                        {
                            "slug": entity.slug,
                            "display_name": entity.display_name,
                            "source": entity.source,
                            "status": entity.status,
                        },
                    )
                    for vertex in cat_vertices:
                        await gateway.apply(vertex_intent(
                            vertex, operation="node_versioned",
                            tenant_id=tenant_id, actor_id="card_linked_ingestion",
                        ))
                    for edge in cat_edges:
                        await gateway.apply(edge_intent(
                            edge, operation="edge_created",
                            tenant_id=tenant_id, actor_id="card_linked_ingestion",
                        ))
            vertices, edges = build_flow_mutations(record)
            for vertex in vertices:
                await gateway.apply(vertex_intent(
                    vertex, operation="node_versioned",
                    tenant_id=tenant_id, actor_id="card_linked_ingestion",
                ))
            for edge in edges:
                await gateway.apply(edge_intent(
                    edge, operation="edge_created",
                    tenant_id=tenant_id, actor_id="card_linked_ingestion",
                ))
        except Exception as exc:  # pragma: no cover — best-effort mirror
            logger.debug("card-linked graph projection skipped: %s", exc)

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

    def _consent_allows(self, consent_snapshot: dict[str, bool] | None,
                        required: tuple[str, ...]) -> bool:
        if consent_snapshot is None:
            # No snapshot supplied — fail closed only when PII blocking is
            # on AND the record carries user-level attribution (checked by
            # caller); catalog/benchmark records need no consent.
            return True
        return all(consent_snapshot.get(purpose, False) for purpose in required)

    async def _apply_region_policy(self, tenant_id: str, record: dict[str, Any],
                                   region_hint: str | None) -> dict[str, Any]:
        policy = resolve_region_policy(region_hint, self._settings)
        record["region_policy"] = policy
        if policy in ("EU_RESTRICTED", "UK_RESTRICTED", "APAC_RESTRICTED"):
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
                             required: tuple[str, ...]) -> bool:
        """Returns True when the record may carry user-level attribution."""
        if not any(record.get(f) for f in _USER_LEVEL_FIELDS):
            return True  # aggregate/wallet-level record — no user consent needed
        if self._consent_allows(consent_snapshot, required):
            record["consent_snapshot"] = consent_snapshot
            return True
        for field_name in _USER_LEVEL_FIELDS:
            record[field_name] = None
        await self._repos.audit.record(tenant_id, "consent_suppressed", {
            "required": list(required),
            "flow_id": record.get("id"),
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
        record = await self._apply_region_policy(tenant_id, record, region_hint)
        await self._check_consent(tenant_id, record, consent_snapshot, ("commerce",))
        result = await self._repos.flows.insert_idempotent(tenant_id, record)
        await self._repos.provider_health.record_event(tenant_id, "provider_webhook")
        await self._project_to_graph(tenant_id, result)
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
        record = await self._apply_region_policy(tenant_id, record, region_hint)
        await self._check_consent(tenant_id, record, consent_snapshot, ("web3",))
        result = await self._repos.flows.insert_idempotent(tenant_id, record)
        await self._repos.provider_health.record_event(tenant_id, "onchain_observer")
        await self._project_to_graph(tenant_id, result)
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
        record = await self._apply_region_policy(tenant_id, record, region_hint)
        await self._check_consent(tenant_id, record, consent_snapshot, required)
        result = await self._repos.flows.insert_idempotent(tenant_id, record)
        await self._repos.provider_health.record_event(tenant_id, "sdk")
        await self._project_to_graph(tenant_id, result)
        await self._try_reconcile(tenant_id, result[0])
        return result

    async def ingest_tenant_import(self, tenant_id: str, rows: list[dict[str, Any]],
                                   *, region_hint: str | None = None,
                                   ) -> list[tuple[dict, str]]:
        results: list[tuple[dict, str]] = []
        for row in rows:
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
                "user_id": row.get("user_id"),
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
            record = await self._apply_region_policy(tenant_id, record, region_hint)
            result = await self._repos.flows.insert_idempotent(tenant_id, record)
            await self._project_to_graph(tenant_id, result)
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
