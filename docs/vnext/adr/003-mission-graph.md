# ADR-003: Mission Graph (Stream-Materialized)

Status: Proposed
Owner: Agent Layer + ML Models
Flag: `AETHER_FEATURE_MISSION_GRAPH` (default: off)

## Context

Today an `Objective` (`Agent Layer/models/objectives.py`) decomposes into
plan steps via `agent_controller/planning/objective_planner.py` and runs in
`agent_controller/runtime/objective_runtime.py`. Outcomes flow into the
attribution service, but reconstructing "what mission was this event part of,
and how did the mission unfold causally over time?" requires running ad-hoc
graph traversals across `objective_events`, attribution edges, and
StagedMutation lineage. The traversals are slow, duplicated across at least
three call sites, and there is no streaming surface — it is a batch query
that times out at scale.

## Decision

A graph query composer plus a feature family.

### Graph composer

Single failure surface: `Agent Layer/shared/graph/composer.py`.

```python
class GraphComposer:
    def __init__(self, client: GraphClient, cache: RedisCache): ...

    def reconstruct_mission(self, objective_id: UUID, *, valid_at: datetime | None = None) -> MissionView:
        """
        Returns:
          {
            objective: Objective,
            steps: list[PlanStep],
            mutations: list[StagedMutation],
            edges: list[CausalEdge],     # weighted from existing attribution
            outcomes: list[OutcomeEvent],
            window: tuple[datetime, datetime],
          }
        """

    def detect_gaps(self, tenant_id: UUID, *, since: datetime) -> list[GapEvent]: ...
    def find_motif(self, name: str, **params) -> list[MotifMatch]: ...   # used by ADR-006
```

Materialized `MissionView` is cached in Redis under
`mission:{objective_id}:{tx_at}` with a TTL of 5 minutes; cache is
invalidated by a Kafka consumer subscribed to the existing
`objective_events`, `staged_mutation_events`, and `attribution_updates`
topics. The composer never queries the graph directly when a fresh cached
view exists.

### Mission features

Single failure surface: `ML Models/aether-ml/features/mission_features.py`.

```python
@feature_family(name="mission", version="v1", schema_hash="...")
class MissionFeatures:
    mission_age_seconds: float
    mission_step_count: int
    mission_branching_factor: float
    mission_attributed_value: float
    mission_anomaly_score: float       # from ADR-006 motif library
    mission_witness_completeness: float  # from ADR-001 witness_status
```

Mission features flow through the existing `features/pipeline.py` and
`features/registry.py`, registered with a schema hash so a bad feature push
does not silently degrade downstream models.

## Consequences

- Touches: `Agent Layer/shared/graph/composer.py` (new), the existing
  attribution service to expose causal weights as a stable read interface,
  `ML/features/pipeline.py` to register the new family, and a new Kafka
  consumer for cache invalidation. The Objective model gains no new
  required fields.
- Does **not** touch: planning algorithm, runtime, KIRA, BOLT, LOOP, or
  TRIGGER controllers. The composer is read-only.
- API impact: new `GET /v2/missions/{objective_id}` endpoint behind the
  flag. No changes to `/v1/objectives/...`.
- Storage: Redis cache footprint scales with active objective count; budget
  in BUILD_SPEC's per-capability cost cap.

## Build sequence

1. Land `composer.py` with `reconstruct_mission` only. Implement against
   the existing graph client; add the Redis cache layer in front. No Kafka
   yet — first version invalidates on TTL only.
2. Add the cache-invalidating Kafka consumer as a separate process under
   `agent_controller/runtime/`. Subscribe to the three topics listed above.
3. Add `MissionFeatures` and register with the feature pipeline. Wire it
   into the existing `POST /v1/ml/predict` path through the standard feature
   join. No model changes required to consume.
4. Add `GET /v2/missions/{objective_id}` thin endpoint that returns the
   cached `MissionView` as JSON. Document the schema in `packages/shared/events.ts`.
5. Add `detect_gaps` (used by Shiki gap inbox) once `reconstruct_mission`
   is stable. `find_motif` is added by ADR-006.

## Failure modes & rollback

- **Cache stampede.** When a hot objective updates, many concurrent
  reconstruction requests pile on. Mitigated by single-flight in the
  composer: the first request computes, others await the in-flight future.
  If single-flight fails (e.g., process restart), the cache TTL bounds
  worst-case duplication.
- **Kafka consumer lag.** When the invalidation consumer falls behind,
  cached views may be stale by up to consumer-lag seconds. Surfaced via
  `mission_cache_lag_seconds`. Reads include a `as_of` timestamp so
  consumers can detect staleness; Shiki shows a "stale by Ns" badge when
  `as_of` lags `now()` by more than 30 s.
- **Composer bug returns wrong mission.** Disable
  `AETHER_FEATURE_MISSION_GRAPH`; the `/v2/missions/...` endpoint returns
  503 and Shiki falls back to its existing per-step view. Mission features
  return the configured null-family default and downstream models continue
  to score (just without the mission signal).
- **Feature family schema hash mismatch.** Pipeline rejects writes to the
  feature store and emits an alert. Models continue with the previous
  schema version until manually rolled.

## Acceptance

- p95 of `GET /v2/missions/{objective_id}` < 250 ms with cache warm,
  < 1.5 s cold, on a fixture with 50-step missions.
- Mission features appear in `features/registry.py` with a stable schema
  hash and successfully feed at least three models without changes to
  their training pipelines.
- Disabling the flag returns the system to v8.8.0 behavior; no model
  predict() call observably regresses on a fixture replay.
