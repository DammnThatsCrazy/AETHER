---
title: Value360 Attribution Confidence Evaluation
slug: api/value360-model-evaluation
section: reference
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 2
source_files:
  - services/api/value/economic/value_confidence_evaluation.py
  - services/api/value/economic/attribution_model_validation.py
  - services/api/value/economic/economic360_provider.py
  - services/api/value/economic/routes.py
  - services/api/alembic/versions/20261104_value_confidence_evaluations.py
  - services/api/alembic/versions/20261104_value_model_approval_policy_evidence.py
source_hashes:
  "services/api/alembic/versions/20261104_value_confidence_evaluations.py": "sha256:a1fe73a59fdb96e4a6f52d449351a15a3eb29bdc4a382240a5cbddac5e1dd1a0"
  "services/api/alembic/versions/20261104_value_model_approval_policy_evidence.py": "sha256:a1ae593245fa190b8ae220494b38735641f40df0d220c50ba70cbf6bfcc52270"
  "services/api/value/economic/attribution_model_validation.py": "sha256:582d2bbef8f45d36d9fbc05217c78541e9b0efd722e52ad16686384eabf6d4d5"
  "services/api/value/economic/economic360_provider.py": "sha256:4779d93a36e749fd3320c2c0039228f73e6e909be63ef4518bbb0455c117c1af"
  "services/api/value/economic/routes.py": "sha256:06f9a6abcc075c506423253e071386eedcc3a7cb88589752e4bfd3cf60235ec7"
  "services/api/value/economic/value_confidence_evaluation.py": "sha256:1c4d7bf7157d3eeb3f4c95aff453ab1dce1d4be47f0ada2bd02fe50dc3332af7"
---

# Value360 attribution confidence evaluation

`POST /v1/economic/attribution-runs/{run_id}/confidence-evaluation` requires an authenticated tenant principal with `write` permission. The service binds the caller and policy decision to an exact completed tenant attribution run and its persisted exact config validation, then persists an append-only evaluation.

The `value-credit-temporal-eligibility.v1` contract evaluates at most 100 canonical credits. Each sample joins its exact tenant/run/conversion/credit IDs to a canonical confirmed, attribution-eligible conversion and exact canonical touchpoint. The metric `temporal_eligibility_accuracy` is the share of sampled credit touchpoints whose observed event time is no later than the conversion event time. Sample rows, exact source IDs, event times, and a deterministic SHA-256 manifest are persisted so Economic360 can rejoin and recompute the result.

This measure evaluates temporal eligibility only. It does not validate that touchpoints caused a conversion, that credit weights represent contribution, that model-reported confidence is calibrated, or that a model generalizes beyond the sampled run. Missing, conflicting, truncated, out-of-scope, or changed source rows leave evaluation evidence unavailable. Causal attribution and global calibration remain unknown.

The window covers both conversion and touchpoint times, including a sample in
which every touchpoint follows its conversion. Future source, authorization or
creation timestamps and malformed sample counts are rejected. The provider
rejoins the exact tenant, completed run, config, validation decision, conversion,
credits and touchpoints before attaching an evaluation reference to a credit
claim. Evaluator identity and the server-recorded permission decision remain
part of its evidence provenance. Current canonical source rows are not
bitemporal; changed or unavailable rows withhold the evaluation.

The separate `model-approval` endpoint requires an authenticated tenant
administrator and persists an append-only approval or rejection with actor,
permission and evaluation time bound to the exact run/config lineage. These
records bind the confidence slot's `model_governance` authority for model
provenance and governed use. The slot remains explicitly model-reported and
uncalibrated. Calibration would require a prediction-to-independently-adjudicated
outcome contract and a reproducible calibration evaluation; temporal eligibility
is not a substitute for that missing evidence.
