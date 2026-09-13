"""Journey processor — applies the FSM, persists journeys, writes the
event_extension sidecar, and emits Iceberg snapshots/exposures.

Pure orchestration: dependencies (repositories, snapshot writer,
ClickHouse client, producer) are injected so the same processor can run
under the streaming consumer or under the nightly batch reconciler.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from .causality import compute as compute_causality
from .journey_fsm import FsmDecision, decide
from .policies import JourneyPolicy, PolicyResolver, attribution_origin


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProcessOutcome:
    journey_id: str
    is_new_journey: bool
    closed_journey_id: Optional[str]
    extension_row: dict


class JourneyProcessor:
    """One processor instance handles many events; not thread-safe per actor."""

    def __init__(
        self,
        *,
        actor_repo,
        journey_repo,
        delegation_repo,
        snapshot_writer,
        clickhouse_writer,           # async fn(table, row) -> None
        producer,                    # EventProducer-like with publish(topic, payload)
        policies: Optional[PolicyResolver] = None,
        history_window: int = 100,
    ) -> None:
        self.actors = actor_repo
        self.journeys = journey_repo
        self.delegations = delegation_repo
        self.snapshots = snapshot_writer
        self.ch_write = clickhouse_writer
        self.producer = producer
        self.policies = policies or PolicyResolver()
        self.history_window = history_window
        self._history: dict[str, list[dict]] = {}   # journey_id -> last N events

    # ------------------------------------------------------------------
    # Public entry — process one validated event from the bus
    # ------------------------------------------------------------------

    async def process(self, event: dict, project_id: str, *, as_of: str = "stream") -> ProcessOutcome:
        policy = await self.policies.get(project_id)
        actor   = await self._resolve_actor(event)
        benef   = await self._resolve_beneficiary(event)
        delegation = await self._resolve_delegation(event, actor)

        open_journey = await self.journeys.find_open(project_id, actor["actor_id"])
        decision: FsmDecision = decide(event=event, open_journey=open_journey, policy=policy)

        closed_journey_id: Optional[str] = None
        is_new = False

        if decision.action in ("close_then_open", "close") and open_journey:
            await self.journeys.close(
                open_journey["journey_id"],
                reason=decision.close_reason or "manual",
                ended_at=event["timestamp"],
            )
            closed_journey_id = open_journey["journey_id"]
            await self.producer.publish("aether.journey.closed", {
                "journey_id": open_journey["journey_id"],
                "reason": decision.close_reason,
                "ended_at": event["timestamp"],
            })
            open_journey = None

        if decision.action in ("open", "close_then_open"):
            preceded_by = (
                (await self.journeys.find_most_recent_closed(project_id, actor["actor_id"]))
                or {}
            ).get("journey_id")
            entry_attr = {
                "origin": attribution_origin(event),
                **((event.get("context") or {}).get("campaign") or {}),
                "captured_at": event["timestamp"],
            }
            open_journey = await self.journeys.open(
                actor_id=actor["actor_id"],
                project_id=project_id,
                entry_event_id=event["id"],
                entry_attribution=entry_attr,
                started_at=event["timestamp"],
                beneficiary_actor_id=(benef or {}).get("actor_id"),
                preceded_by_journey_id=preceded_by,
            )
            is_new = True

        # Always extend the (possibly newly opened) journey
        await self.journeys.extend(
            open_journey["journey_id"],
            event_ts=event["timestamp"],
            session_id=event.get("sessionId"),
        )

        # Conversion handling — keeps the journey open, but stamps it
        if decision.is_conversion:
            jrn = await self.journeys.close(
                open_journey["journey_id"],
                reason="conversion",
                ended_at=event["timestamp"],
                conversion_event_id=event["id"],
            )
            # immediately reopen for retention analytics? policy decision —
            # for v1 we keep it converted+ended; later events that arrive
            # for this actor will spawn a new journey via the inactivity
            # gate or a fresh-origin gate.
            await self.producer.publish("aether.journey.converted", {
                "journey_id": jrn["journey_id"],
                "actor_id": actor["actor_id"],
                "conversion_event_id": event["id"],
            })

        # Causality + snapshots + extension row
        history = self._history.setdefault(open_journey["journey_id"], [])
        causal = compute_causality(event=event, journey_history=history)

        snap_ref = await self.snapshots.write_state_snapshot(
            project_id=project_id,
            event_id=event["id"],
            event_date=event["timestamp"][:10],
            user_state=self._user_state(event, actor),
            system_state=self._system_state(event),
        )
        exposure_ref = await self.snapshots.write_exposures(
            project_id=project_id,
            event_id=event["id"],
            event_date=event["timestamp"][:10],
            impressions=((event.get("context") or {}).get("impressions") or []),
        )

        ext = self._build_extension_row(
            event=event,
            project_id=project_id,
            actor=actor,
            beneficiary=benef,
            journey=open_journey,
            delegation=delegation,
            snapshot_ref=snap_ref,
            exposure_ref=exposure_ref,
            causal=causal,
            as_of=as_of,
        )
        await self.ch_write("event_extension", ext)

        # Maintain bounded per-journey history
        history.append(event)
        if len(history) > self.history_window:
            del history[: len(history) - self.history_window]

        return ProcessOutcome(
            journey_id=open_journey["journey_id"],
            is_new_journey=is_new,
            closed_journey_id=closed_journey_id,
            extension_row=ext,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _resolve_actor(self, event: dict) -> dict:
        ctx = event.get("context") or {}
        actor_kind = ctx.get("actorKind") or ("agent" if event.get("type", "").startswith("agent_") else "human")
        identifier = ctx.get("actorId") or event.get("userId") or event.get("anonymousId")
        return await self.actors.get_or_create(
            kind=actor_kind,
            identifier=identifier,
            tenant_id=ctx.get("tenantId", ""),
            org_id=ctx.get("orgId", ""),
        )

    async def _resolve_beneficiary(self, event: dict) -> Optional[dict]:
        ctx = event.get("context") or {}
        ben = ctx.get("beneficiaryActorId")
        if not ben:
            return None
        return await self.actors.get_or_create(
            kind="human", identifier=ben, tenant_id=ctx.get("tenantId", "")
        )

    async def _resolve_delegation(self, event: dict, actor: dict) -> Optional[dict]:
        ctx = event.get("context") or {}
        delegation_id = ctx.get("delegationId")
        if not delegation_id:
            return None
        scope = ctx.get("delegationScope") or [event.get("type", "")]
        # authorize() also caches; here we only return the resolved record
        return await self.delegations.authorize(
            delegatee_actor_id=actor["actor_id"],
            required_scope=scope,
        )

    @staticmethod
    def _user_state(event: dict, actor: dict) -> dict:
        return {
            "actor_id": actor["actor_id"],
            "actor_kind": actor.get("kind"),
            "consent": (event.get("context") or {}).get("consent") or {},
            "fingerprint": (event.get("context") or {}).get("fingerprint") or {},
        }

    @staticmethod
    def _system_state(event: dict) -> dict:
        ctx = event.get("context") or {}
        return {
            "page": ctx.get("page"),
            "device": ctx.get("device"),
            "campaign": ctx.get("campaign"),
            "library": ctx.get("library"),
            "experiments": (event.get("properties") or {}).get("experiments"),
        }

    @staticmethod
    def _build_extension_row(
        *,
        event: dict,
        project_id: str,
        actor: dict,
        beneficiary: Optional[dict],
        journey: dict,
        delegation: Optional[dict],
        snapshot_ref,
        exposure_ref: Optional[str],
        causal: dict,
        as_of: str,
    ) -> dict:
        ctx = event.get("context") or {}
        props = event.get("properties") or {}
        first_touch = journey.get("entry_attribution") or {}
        camp = ctx.get("campaign") or {}

        return {
            "event_id": event["id"],
            "event_date": event["timestamp"][:10],
            "project_id": project_id,

            "actor_id": actor["actor_id"],
            "actor_kind": actor.get("kind"),
            "beneficiary_actor_id": (beneficiary or {}).get("actor_id"),

            "journey_id": journey["journey_id"],
            "journey_sequence": journey.get("event_count", 0),

            "attribution_first_touch": (
                first_touch.get("source", "direct"),
                first_touch.get("campaign", ""),
                first_touch.get("captured_at") or event["timestamp"],
            ),
            "attribution_last_touch": (
                camp.get("source", "direct"),
                camp.get("campaign", ""),
                event["timestamp"],
            ),
            "attribution_multi_touch": {},        # filled by nightly batch
            "attribution_actor_weighted": {},     # filled by nightly batch

            "snapshot_ref": snapshot_ref.uri,
            "snapshot_hash": snapshot_ref.hash,

            "ts_relative_journey_ms": _diff_ms(journey.get("started_at"), event["timestamp"]),
            "ts_relative_session_ms": 0,         # requires session-start lookup
            "ts_relative_prev_ms": 0,            # filled by batch over ordered events

            "triggered_by_event_id": causal["triggered_by_event_id"],
            "influencing_event_ids": causal["influencing_event_ids"],
            "causal_score": causal["causal_score"],

            "decision_options": (props.get("decisionOptions") or ""),

            "exposure_ref": exposure_ref or "",

            "friction": _coerce_str_map(props.get("friction") or {}),
            "engagement": _coerce_float_map(props.get("engagement") or {}),
            "intent": (
                (props.get("intent") or {}).get("predictedGoal", ""),
                float((props.get("intent") or {}).get("confidence", 0.0)),
            ),
            "environment": _coerce_str_map({
                "device_type": (ctx.get("device") or {}).get("type"),
                "os": (ctx.get("device") or {}).get("os"),
                "browser": (ctx.get("device") or {}).get("browser"),
                "locale": ctx.get("locale"),
                "timezone": ctx.get("timezone"),
            }),

            "identity_confidence": float(ctx.get("identityConfidence", 0.5)),
            "identity_signals": list(ctx.get("identitySignals") or []),

            "delegation_id": (delegation or {}).get("delegation_id"),
            "delegation_scope": list((delegation or {}).get("scope") or []),

            "agent_reasoning_ref": (props.get("agentReasoningRef") or ""),
            "agent_confidence": float(props.get("agentConfidence", 0.0)),
            "agent_policy_logs": list(props.get("agentPolicyLogs") or []),

            "economic": _coerce_str_map(props.get("economic") or {}),
            "system_actions": (props.get("systemActions") or ""),

            "consent": _coerce_uint_map(ctx.get("consent") or {}),
            "data_quality": _coerce_float_map(props.get("dataQuality") or {
                "completeness": 1.0,
                "freshness": 1.0,
                "source_trust": 1.0,
            }),

            "as_of": as_of,
        }


# ----------------------------------------------------------------------
# small coercion helpers — ClickHouse Map<String, T> wants stringly keys
# ----------------------------------------------------------------------

def _coerce_str_map(d: dict) -> dict:
    return {str(k): "" if v is None else str(v) for k, v in d.items()}


def _coerce_float_map(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        try: out[str(k)] = float(v)
        except (TypeError, ValueError): pass
    return out


def _coerce_uint_map(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, bool): out[str(k)] = 1 if v else 0
        elif isinstance(v, (int, float)): out[str(k)] = int(bool(v))
    return out


def _diff_ms(start_iso: Optional[str], end_iso: Optional[str]) -> int:
    if not start_iso or not end_iso:
        return 0
    fmt = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    return int((fmt(end_iso) - fmt(start_iso)).total_seconds() * 1000)
