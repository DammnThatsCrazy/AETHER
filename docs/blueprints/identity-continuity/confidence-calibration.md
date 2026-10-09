---
title: Identity Confidence Evaluation
slug: blueprints/identity-continuity/confidence-calibration
section: blueprints
visibility: P
audience: [dev-senior, architect]
status: beta
---

# Identity Confidence Evaluation

## Contract

`score_signals` emits an `identity_match_score`: an ordinal, evidence-weighted
strength of match. It is not a probability that two records describe the same
identity. The offline evaluator in
`services/backend/services/identity/calibration_evaluation.py` preserves that
distinction. It measures reviewed decision errors and empirical same-identity
rates within score bands. The score-to-rate gap is descriptive and is not a
calibration error. Brier score, log loss, and probabilistic claims are
intentionally absent.

Every reviewed JSONL row must carry a unique `decision_id`, a finite `score` in
`[0, 1]`, a boolean `same_identity`, `runtime_action` (`merge`, `no_merge`, or
`review`), `label_source: "human_review"`, a pseudonymous `tenant_ref` with a
`tenant:` prefix, `source_family`, a pseudonymous `adjudicator_ref` with a
`reviewer:` prefix, timezone-aware `adjudicated_at`, and
`independent_review: true`. Rows missing these fields or claiming dependent
review are rejected. Raw tenant or reviewer identifiers must not be exported.
A false merge is a runtime merge
whose adjudicated label is different identity. A false non-merge is an explicit
`no_merge` action whose label is same identity. Review actions contribute to
the sample and score-band reliability table, but not to either error count.

## Evidence gates

The CLI requires, by default, 500 reviewed pairs total; at least three distinct
opaque tenant references and two source families; at least 30 pairs in
each score band; at least 10 positive and 10 negative labels in each band; and
a 95% Wilson interval half-width no greater than 0.15 in every band. The
defaults can be tightened or adjusted explicitly for an evaluation run. The
report says `insufficient_labels`, `insufficient_provenance`, or
`insufficient_band_support` when those requirements are not met. The
`evidence_sufficient_for_policy_review` flag requires all three gates. It says
`evaluation_evidence_sufficient_for_policy_review` only when all are met.

That status authorizes a separate policy review only. It does not establish
that labels represent the intended tenant, provider, SDK, time period, or
operating prevalence; an independently sampled holdout and approved error
budgets are still required. The report always returns
`production_calibrated: false`, `runtime_policy_changed: false`, and
`resolver_thresholds_changed: false`. It neither fits a probability mapping nor
mutates runtime confidence flags or thresholds.

## Current evidence limits

The repository currently has behavioral scenario fixtures, not a representative
human-adjudicated identity-pair dataset. Those fixtures prove selected expected
behaviors and are useful for evaluator tests, but they cannot estimate real
false-merge prevalence, false-non-merge prevalence, score-band reliability, or
tenant/source calibration. No production confidence calibration can be claimed
until reviewed labels with provenance, source/tenant/time coverage, adequate
band support, and an independent holdout are collected.

## Human review intake

The intake helper converts authorized identity review evidence into a blinded
annotation packet without treating the resolver's action as the answer. First,
an authorized tenant or operator evidence export must be reduced to the exact
metadata-only JSONL fields below. `decision_id`, `pair_ref`, tenant, and reviewer
values must already be opaque references; raw identity claims, contact values,
source payloads, or credentials are rejected by the narrow field contract.

```json
{"decision_id":"decision_opaque_0001","pair_ref":"pair_opaque_0001","tenant_ref":"tenant:opaque-tenant-0001","score":0.82,"runtime_action":"review","source_family":"commerce","original_decider_ref":"reviewer:opaque-actor-0001","evidence_origin":"tenant_identity_review","non_fixture":true}
```

The evidence origin must be a tenant or operator identity review, and
`non_fixture` must be true. Synthetic scenarios and test decisions are
explicitly rejected. The reviewer uses the opaque pair reference to inspect the
current authorized identity evidence in Aether, then fills a separate blinded
annotation file. The packet omits score, runtime action, and tenant reference
to reduce anchoring and unnecessary disclosure. Store the private join file
separately from the packet and annotations with access restricted to the
evaluation operator.

```bash
export IDENTITY_CALIBRATION_INTAKE_HMAC_KEY="<random secret of at least 32 bytes>"
python scripts/identity_confidence_calibration_intake.py prepare \
  authorized-review-evidence.jsonl calibration-intake/
# An independent reviewer fills annotation-packet.jsonl, preserving case_ref
# and pair_ref, and submits only these fields:
# case_ref, same_identity, adjudicator_ref, adjudicated_at, independent_review
python scripts/identity_confidence_calibration_intake.py assemble \
  calibration-intake/annotation-packet.jsonl \
  calibration-intake/private-join.jsonl \
  completed-annotations.jsonl reviewed-pairs.jsonl
python scripts/identity_confidence_calibration_evaluation.py reviewed-pairs.jsonl \
  --output calibration-report.json
```

The HMAC-derived case and decision references are stable only within the secret
key's scope. The key is not written to disk by the helper. Output files are
created with owner-only permissions, and existing output files cause an error
instead of being overwritten. Assembly requires exact case-set agreement,
explicit boolean labels, a timezone-aware timestamp, a pseudonymous annotator,
and an explicit independent-review attestation. The annotator must differ from
the original decision maker. No user identity data is included in the evaluator
rows. The assembled file is still only a candidate reviewed-label dataset; a
human must actually complete the annotations, and independent holdout and
coverage gates still apply.

## Run

```bash
python scripts/identity_confidence_calibration_evaluation.py reviewed-pairs.jsonl \
  --bins 10 \
  --minimum-labels 500 \
  --minimum-per-band 30 \
  --minimum-each-class-per-band 10 \
  --minimum-tenants 3 \
  --minimum-source-families 2 \
  --maximum-interval-half-width 0.15 \
  --output calibration-report.json
```

The command writes a versioned JSON report and does not update resolver
configuration. Keep reviewed source labels access-controlled and store the
result alongside the evaluation's sampling and adjudication protocol.
