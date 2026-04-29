# ADR-006: Collusion Motif Detection

Status: Proposed
Owner: Backend Architecture
Flag: `AETHER_FEATURE_MOTIFS` (default: off)

## Context

Fraud and anomaly services
(`Backend Architecture/aether-backend/services/fraud/` and
`shared/scoring/anomaly_config.py`) score per-actor and per-event signals
well, but they are blind to coordinated multi-actor patterns: ring trades,
wash flows, sybil attestation rings, and synthetic ecosystem activity that
looks fine actor-by-actor and only reveals itself as a graph motif. Today
those motifs are caught (when at all) by ad-hoc analyst queries, not by
the system.

## Decision

A library of named graph motifs, each a parameterized subgraph pattern,
plus an integration into the existing fraud/anomaly pipeline.

Single failure surface:
`Backend Architecture/aether-backend/shared/motifs/library.py`.

```python
@motif(name="ring_trade", version="v1")
class RingTrade(Motif):
    params = {"min_cycle_length": 3, "max_cycle_length": 6, "window_seconds": 3600}
    def match(self, g: GraphView, **p) -> Iterator[MotifMatch]: ...

@motif(name="sybil_attestation_ring", version="v1")
class SybilAttestationRing(Motif): ...

@motif(name="wash_flow", version="v1")
class WashFlow(Motif): ...

@motif(name="reciprocal_review", version="v1")
class ReciprocalReview(Motif): ...

@motif(name="synthetic_ecosystem", version="v1")
class SyntheticEcosystem(Motif): ...
```

Each `Motif.match` returns `MotifMatch` instances containing the matched
subgraph, the strength score, and the participating principal IDs.
Motifs are evaluated by a Kafka consumer subscribed to graph-mutation
topics; matches are written to a new `motif_matches` table and emitted as
`motif_detected` events.

The fraud service consumes `motif_detected` events and feeds them into
its existing scoring path as additional features (via the feature
pipeline). The anomaly service does the same for its threshold logic. No
fraud or anomaly logic is replaced — motifs are an additional input.

## Consequences

- Touches: new `shared/motifs/` directory; a new Kafka consumer for motif
  evaluation; the fraud service's feature consumer (additive); the anomaly
  service's threshold input (additive); Shiki gets a new alerts panel
  (`apps/shiki/src/components/alerts-panel.tsx`) consuming the existing
  WebSocket — handled in a follow-up SK PR.
- Does **not** touch: fraud scoring algorithm, anomaly thresholds, graph
  schema (motifs read existing edges).
- API impact: new `GET /v2/motifs/matches?...` for analyst inspection.
  No `/v1/...` changes.
- Storage: `motif_matches` table grows with detection rate. Partitioned
  by detection time; closed matches archive to cold storage after
  retention window.

## Build sequence

1. Land the `Motif` base class, the registration decorator, and the
   `library.py` module that imports the registered motifs. No motif
   implementations yet.
2. Implement `ring_trade` first — it is the most common pattern and gives
   the clearest end-to-end test signal.
3. Stand up the motif evaluator as a separate Kafka consumer process
   under `Backend Architecture/aether-backend/services/`. Subscribe to
   graph-mutation topics; for each batch, evaluate registered motifs over
   the affected subgraph and write matches.
4. Wire `motif_detected` events into the fraud service's feature path
   through the standard feature pipeline. Verify fraud scores are
   bit-identical when no motifs match (additivity check).
5. Implement remaining motifs one at a time. Each ships behind its own
   sub-flag (`AETHER_FEATURE_MOTIF_<NAME>`) so a buggy motif can be
   disabled without taking the others down.
6. Land the `find_motif` method on the ADR-003 graph composer, delegating
   to the same library — Shiki, fraud service, and the composer all
   share one motif implementation per name.

## Failure modes & rollback

- **A motif matches everything (false positive blast).** Per-motif flag
  flips off in <1 min; the noisy motif stops emitting `motif_detected`
  events; the fraud service's feature returns the configured null-family
  default for that motif. No fraud-scoring regressions because motifs
  are additive features.
- **Motif evaluator falls behind.** Detection lag is surfaced as
  `motif_eval_lag_seconds`. The fraud and anomaly services continue
  operating on whatever motif features are available; staleness is a
  signal-quality issue, not an availability one.
- **Subgraph matching is too slow on a large graph.** Each motif runs
  with a per-evaluation budget (rows scanned, time elapsed). Exceeding
  budget aborts the evaluation, emits a metric, and continues to the
  next batch. Partial matches are not emitted.
- **Disable the capability.** `AETHER_FEATURE_MOTIFS=off` stops the
  evaluator and the fraud/anomaly services revert to their v8.8.0
  feature inputs.

## Acceptance

- `ring_trade` correctly identifies a planted cycle in a synthetic
  fixture with precision ≥ 0.95 at recall ≥ 0.9.
- All five motifs have at least one regression test that asserts
  matching and non-matching subgraphs.
- Fraud service feature inputs include `motif_*` features within
  60 s of the originating graph mutation under nominal Kafka lag.
- Disabling either the umbrella flag or any per-motif sub-flag returns
  the system to v8.8.0 behavior on a fixture replay; fraud scores are
  bit-identical when no motifs match.
