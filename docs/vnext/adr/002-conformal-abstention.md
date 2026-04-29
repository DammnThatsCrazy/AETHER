# ADR-002: Conformal Abstention + Explainability Wrapper

Status: Proposed
Owner: ML Models
Flag: `AETHER_FEATURE_CONFORMAL` (default: off; per-model opt-in via
`MODEL_CONFORMAL_<NAME>=on`)

## Context

All nine production models in `ML Models/aether-ml/` return point scores via
`predict()`. Downstream consumers (StagedMutation creation, fraud routing,
trust scoring) treat every score as a confident answer, with no signal of
*how confident*. This degrades silently when a tenant is new (no behavioral
history), when feature distributions drift, or when the input falls outside
the training manifold. Reviewers in Shiki see a staged mutation with no
explanation of why or what evidence supports it.

## Decision

A single conformal wrapper that every model passes through.

Single failure surface: `ML Models/aether-ml/common/src/conformal.py`.

```python
@dataclass
class PredictResult:
    score: float
    lower: float
    upper: float                  # 1 − alpha prediction interval
    abstain: bool
    abstain_reason: str | None    # "calibration_too_small" | "ood" | "interval_too_wide" | None
    top_features: list[tuple[str, float]]   # (feature_name, shapley-style attribution)
    evidence_ids: list[str]                 # links to StagedMutation.supporting_fact_ids

def conformal_predict(
    model: BaseModel,
    x: FeatureRow,
    *,
    alpha: float = 0.10,
    calibration: CalibrationSet,
    explain: bool = True,
) -> PredictResult: ...
```

Calibration sets are versioned and per-tenant, stored alongside the model in
the existing model registry. Cold-start tenants begin with
`calibration.size < CALIBRATION_MIN`, in which case `abstain=True` with
`abstain_reason="calibration_too_small"` until enough holdout examples
accumulate (default `CALIBRATION_MIN=200`).

## Consequences

- Touches: `ML/serving/src/api.py` to thread `PredictResult` through
  `POST /v1/ml/predict` (additive fields, score field unchanged for
  back-compat); each of the nine model `predict()` methods to call through
  the wrapper instead of returning a bare score.
- Does **not** touch: feature pipeline, training pipeline, model registry
  schema (calibration is a sidecar, not a registry change).
- API impact: response gains `interval`, `abstain`, `top_features`,
  `evidence_ids` fields. Existing `score` field is unchanged. Consumers
  ignoring the new fields continue to work.
- StagedMutation gains an optional `confidence_band: {lower, upper}` and
  `abstained: bool` written from the wrapper output. Reviewers see this in
  Shiki's review page (handled by the SK side in a follow-up PR; flag-gated
  by the same env var).

## Build sequence

1. Land `conformal.py` with the wrapper, plus a `CalibrationSet`
   abstraction backed by the existing model registry blob storage.
2. Add the explainability hook: SHAP for tree models (already a dependency
   for at least the fraud model), integrated gradients for sequence models.
   The `explain` flag short-circuits when the cost budget for the request
   is exhausted (see capability cost circuit breakers in BUILD_SPEC).
3. Wire one model through the wrapper end-to-end (recommend: trust score, the
   simplest and most-consumed). Validate that `score` field is bit-identical
   to pre-wrapper output when `abstain=False`.
4. Roll the remaining eight models behind individual
   `MODEL_CONFORMAL_<NAME>` flags. Default off; flip per-model after one
   week of advisory-mode metrics.
5. Extend `POST /v1/ml/predict` to thread the new fields through.
   Update `packages/shared/events.ts` with the additive optional fields
   under `experimental.conformal` until the ADR is Accepted.
6. Drift monitor: once `MODEL_CONFORMAL_*` is on for a model, compute PSI
   between current input distribution and the calibration set; alert when
   PSI > 0.2 for any feature (this is the data drift monitor referenced in
   BUILD_SPEC).

## Failure modes & rollback

- **Wrapper bug returns garbage interval.** Per-model flag flips off,
  reverting to bare `score`. The wrapper enforces `lower <= score <= upper`
  as a runtime assertion; assertion failures surface in
  `conformal_assertion_failures_total` and cause that single inference to
  fall back to the unwrapped score (logged, not exception).
- **Calibration set drift makes everything abstain.** Surfaced via
  `conformal_abstain_rate{reason="interval_too_wide"}`. Operator response is
  to retrain or refresh calibration set; the system does not block.
- **Explainability cost blows up.** SHAP on a wide feature row is
  expensive. Per-request explain is bounded by a token budget enforced in
  the wrapper; if exceeded, return `top_features=[]` and emit a metric.
  Consumers (Shiki review page) treat empty `top_features` as
  "explanation unavailable".

## Acceptance

- All nine models opt-in to the wrapper; per-model abstention rate stays
  below 5 % in steady state for established tenants.
- Cold-start tenants reliably see `abstain=True` with
  `abstain_reason="calibration_too_small"` until `CALIBRATION_MIN`
  examples accumulate; no spurious confident scores in this window.
- Shiki review page shows `top_features` for at least 80 % of staged
  mutations once the SK-side PR lands.
- Disabling `AETHER_FEATURE_CONFORMAL` returns every `predict()` call to
  v8.8.0 behavior with byte-identical responses on a fixture replay.
