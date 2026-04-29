# ADR-005: Coverage Autopilot — Active-Learning Router

Status: Proposed
Owner: Agent Layer
Flag: `AETHER_FEATURE_AL_ROUTER` (default: off)

## Context

ReviewBatcher today sends every staged mutation that crosses the
configured uncertainty/risk threshold into the human review queue. This
under-utilizes reviewer attention: easy decisions waste cycles, hard ones
arrive in arbitrary order, and the system collects no labeled-outcome
signal in the right shape to train a smarter policy later. The result is
that label coverage of the decision space is uneven, and a future DPO
trainer (deferred per BUILD_SPEC) will not have the right data.

## Decision

A thin active-learning router sitting between ReviewBatcher and the human
queue.

Single failure surface: `Agent Layer/agent_controller/learning/al_router.py`.

```python
class ALRouter:
    def __init__(self, batcher: ReviewBatcher, policy: ALPolicy): ...

    def route(self, mutation: StagedMutation, predict: PredictResult) -> Routing:
        """
        Returns one of:
          ROUTE_AUTO_APPROVE     # confidence high, low risk, in-distribution
          ROUTE_AUTO_REJECT      # confidence high it should not commit
          ROUTE_HUMAN(priority)  # uncertainty or risk warrants a human; priority drives queue order
          ROUTE_SHADOW           # commit to a shadow lane for outcome labeling, no graph effect
        """
```

`ALPolicy` is a small composable scorer:

```python
class ALPolicy:
    def score(self, m: StagedMutation, p: PredictResult) -> RoutingScore:
        # combines:
        #   - p.upper - p.lower          (interval width / uncertainty)
        #   - p.abstain                  (forces human or shadow)
        #   - m.estimated_blast_radius   (existing field)
        #   - m.reversibility            (existing field)
        #   - coverage_gap(m.feature_row)  (uncertainty in calibration set neighborhood)
        ...
```

`coverage_gap` is the only new computation: distance from the mutation's
feature row to the nearest k calibration examples, normalized per-tenant.
It is computed against the same `CalibrationSet` introduced in ADR-002.

Every routing decision and its eventual outcome is emitted as a
`review_routing_outcome` event onto Kafka. This is the dataset that a
future DPO trainer (deferred) will consume.

## Consequences

- Touches: ReviewBatcher (calls into the router instead of going straight
  to the human queue), StagedMutation (gains `routing_decision` and
  `routing_score` optional fields), and a new outcome event type on Kafka.
- Does **not** touch: planning, runtime, attribution, or KIRA decision
  loop. The router never modifies the mutation; it only decides where it goes.
- API impact: none on `/v1/...`. New `GET /v2/review/routing/{mutation_id}`
  for debugging routing decisions.
- StagedMutation gains `rollback_mutation_id` (the inverse mutation that
  reverts a previously committed one). This is the rollback story
  referenced in BUILD_SPEC and is needed because auto-approve in
  ROUTE_AUTO_APPROVE without a rollback path would be unsafe.

## Build sequence

1. Land `al_router.py` with all four routing decisions and a default
   policy. ROUTE_AUTO_APPROVE is **disabled** by default — the policy
   returns ROUTE_HUMAN for everything that would have been auto-approved,
   even with the flag on, so the router is shadow-mode safe at landing.
2. Add `routing_decision` and `routing_score` columns to StagedMutation
   (additive, nullable). Emit `review_routing_outcome` on every routing
   decision and on every eventual reviewer outcome.
3. Add `rollback_mutation_id` to StagedMutation. Implement
   `StagedMutation.rollback()` that creates the inverse mutation, links
   the two, and stages the inverse for review at high priority. Auto-approve
   may not be enabled until rollback is implemented for every mutation
   class actually emitted in production.
4. Add the `coverage_gap` computation against the ADR-002 calibration set.
   Cache distances per tenant to bound cost.
5. Land ROUTE_SHADOW: a parallel commit lane that writes mutations to a
   shadow-only namespace in the graph (no downstream effect) so we can
   label outcomes without taking action. This is the AL data engine.
6. Enable ROUTE_AUTO_APPROVE per-tenant, per-mutation-class, only after
   ≥ 1 000 reviewer outcomes have been collected and the policy's recall
   on "should approve" exceeds 99 % at < 1 % false-approve rate on the
   labeled set.

## Failure modes & rollback

- **Auto-approve fires on a mutation that should have been rejected.**
  Caught by:
    - the ADR-002 conformal abstention gate (mutations with `abstain=True`
      never auto-approve regardless of policy),
    - the rollback mutation that any consumer can stage to revert,
    - the router's own per-class auto-approve flag, flippable in <1 min.
- **Router computes a bad routing score.** ROUTE_HUMAN is the default
  fallback when the score is invalid (NaN, or out of expected range).
  Surfaced via `al_router_invalid_score_total`.
- **Calibration set is empty for a new tenant.** `coverage_gap` returns
  `inf`; policy routes to ROUTE_HUMAN. Cold-start tenants thus never
  auto-approve until the conformal calibration set is warm — the same
  cold-start gate as ADR-002.
- **Disable the capability.** `AETHER_FEATURE_AL_ROUTER=off` reverts
  ReviewBatcher to its v8.8.0 behavior of routing everything that crosses
  threshold to human review.

## Acceptance

- ROUTE_SHADOW lane is operational and emits `review_routing_outcome`
  events for ≥ 90 % of staged mutations once the flag is on (the rest are
  legitimate ROUTE_HUMAN at landing).
- StagedMutation gains a working `rollback()` for every mutation class
  emitted in the last 30 days of production traffic.
- Reviewer outcome events are well-structured enough to train a DPO
  policy later (verified by a synthetic trainer dry-run; trainer itself
  remains deferred).
- Disabling the flag returns the system to v8.8.0 behavior; no review
  decision is silently auto-applied.
