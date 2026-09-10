---
title: "Aether Canonical Semantic + Rights Authority — Implementation Blueprint"
slug: architecture/rights-authority-blueprint
section: architecture
visibility: I
audience: [architect, dev-senior, exec, compliance]
status: experimental
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 25
toc_depth: 3
---

# Aether Canonical Semantic + Rights Authority
## Rights Retention, Learning & Olympus Intelligence — Implementation Blueprint

**Product:** Aether · **Company:** Olympus Labs · **Operator plane:** Kyber
**Architecture class:** Spine-level canonical authority extension
**Primary governed spine:** `rights_irrl`
**Governing substrate:** Contract Spine + Spine Composition Kernel
**Implementation posture:** Extension/convergence of existing authorities; **no parallel rights platform**
**Target state:** `rights_irrl` → `canonical` only after conformance, enforcement, migration, and runtime evidence are complete.

This document is the in-repo, source-of-truth version of the Aether Rights Authority
blueprint. It supersedes the earlier proposal to create an independent IRRL runtime,
independent IRRL registry, independent retention authority, or a second rights ledger
(ADR-011 D2/D4 forbid parallel registries). It is the canonical implementation contract:
all implementer streams must code against the field and vocabulary names frozen in this
document.

---

# 1. Doctrine

## 1.1 Canonical doctrine

> **Contribution rights, ownership rights, use rights, retention rights, derivation rights,
> learning rights, disclosure rights, portability rights, and deletion rights are separate
> authorities.**

## 1.2 Commercial doctrine

> **Tenant ownership of contributed information does not automatically create ownership of
> every intelligence artifact Aether generates from that information.**

## 1.3 Trust doctrine

> **Olympus proprietary rights over Aether-generated intelligence do not create unrestricted
> authority to expose tenant-identifiable or tenant-confidential information to another tenant
> or external party.**

## 1.4 The exchange

```text
TENANT contributes information → AETHER (infrastructure + computation + semantics + models + graph reasoning)
  → GENERATED INTELLIGENCE → Tenant receives governed usage rights; Olympus retains governed proprietary / learning rights.
```

Aether compounds knowledge while remaining a governed enterprise platform rather than a
conventional customer-data broker.

## 1.5 Architectural reconciliation

`rights_irrl` is a **composition and decision authority** inside the Contract Spine (via the
Spine Composition Kernel) over existing authorities — `DataRightsGrant`,
`ConsentPolicyDecision`, `DataRetentionPolicy`, DSR propagation, storage lifecycle,
evidence + lineage, model governance, and the Graph Mutation Gateway. It is **not** another
platform inside Aether.

---

# 2. Final rights taxonomy

Four primary information classes. Ownership/authority must **never** be encoded as one
`owner` field with all downstream permissions inferred. For every governed artifact the
platform resolves independently: OWNERSHIP, USE AUTHORITY, RETENTION AUTHORITY,
DERIVATION AUTHORITY, LEARNING AUTHORITY, DISCLOSURE AUTHORITY, COMMERCIALIZATION
AUTHORITY, PORTABILITY AUTHORITY, DELETION AUTHORITY, SURVIVAL AUTHORITY.

## 2.1 Class I — Contributed Information
Originates outside Aether (SDK observations, tenant imports, CRM, payment info, provider
data, tenant-owned identity, webhooks, campaign info). Property interest normally remains
with tenant / data subject / source provider / contractual licensor; Aether receives
governed use rights.

## 2.2 Class II — Canonicalized Information
Operationally transformed without substantial new intelligence (normalized records,
schema-converted events, canonical timestamps, currency normalization, resolved provider
IDs, normalized geo refs, canonical asset IDs). Source rights continue to govern;
transformation does not create an Olympus-exclusive asset.

## 2.3 Class III — Aether Generated Intelligence
Produced through meaningful Aether computation (identity resolution, clusters, relationship
fidelity, risk assessments, fraud hypotheses, attribution, outcomes, journeys, inferred
episodes, predictions, recommendations, findings, anomaly classifications, value
projections, generalized patterns, graph-derived features, model-derived classifications).
**Commercial default:** Olympus retains proprietary rights in the Aether-created
computational artifact; tenant receives broad contractual rights to use the result for its
business. Never treated as equivalent to raw tenant data.

## 2.4 Class IV — Generalized Aether Knowledge
Aether-generated artifact that passed the **Generalization Gateway** and no longer exposes
prohibited tenant-identifiable/tenant-confidential information (generalized fraud patterns,
behavioral motifs, ontology improvements, resolver calibration, aggregate benchmarks,
non-identifying feature distributions, generalized graph patterns, population trends,
schema mappings, model improvements, protocol classification). May become durable Olympus
intellectual capital where rights permit.

---

# 3. Canonical contract model (frozen field contract)

`DataRightsGrant` remains the canonical source/use-right authority and is upgraded from
source-data permissions into a structured rights contract via **nested governed components**
(no dozens of unrelated top-level booleans).

```python
class DataRightsGrant:
    data_rights_grant_id: str
    tenant_id: str
    contract_id: Optional[str]
    source_id: str
    connector_id: str
    connector_class: str
    raw_data_owner: str

    source_use: SourceUseAuthority
    generated_output_rights: GeneratedOutputRights
    learning_authority: LearningAuthority
    disclosure_authority: DisclosureAuthority
    retention_authority: RetentionAuthority
    termination_authority: TerminationAuthority

    legal_basis: str
    consent_basis: Optional[str]
    subject_ref: Optional[str]

    granted_at: str
    expires_at: Optional[str]
    revoked_at: Optional[str]
    status: str
```

## 3.1 SourceUseAuthority (migrates existing booleans; no semantic change on migration)

```yaml
source_use:
  tenant_lake: true
  tenant_graph: true
  tenant_insights: true
  olympus_baseline: false
  cross_tenant_aggregate: false
  commercial_reuse: false
```

## 3.2 GeneratedOutputRights (primary Olympus-strengthening contract)

```yaml
generated_output_rights:
  proprietary_holder: olympus

  tenant_license:
    view: true
    use: true
    reproduce: true
    integrate: true
    export: true
    internal_commercial_use: true

  olympus:
    retain: true
    analyze: true
    transform: true
    derive: true
    platform_improvement: true
    internal_research: true

  external_disclosure:
    identifiable: false
    generalized: governed

  survival:
    tenant_exported_outputs: true
    olympus_generalized_derivatives: true
```

## 3.3 LearningAuthority (replaces the single `model_training_allowed`)

Learning classes (mandatory canonical vocabulary):

```text
INFERENCE
TENANT_ADAPTATION
GENERALIZED_LEARNING
RESOLVER_CALIBRATION
ONTOLOGY_LEARNING
SCHEMA_MAPPING_LEARNING
BENCHMARKING
CONTRIBUTED_MODEL_TRAINING
OLYMPUS_INTERNAL_INTELLIGENCE
```

```yaml
learning_authority:
  inference: true
  tenant_adaptation: true
  generalized_learning: true
  resolver_calibration: true
  ontology_learning: true
  schema_mapping_learning: true
  benchmarking: true
  contributed_model_training: false
  olympus_internal_intelligence: true
```

A tenant may allow generalized learning while refusing raw-data model training.

**Backward-compatibility migration map (must NOT broaden silently):**

```text
model_training_allowed  ──►  contributed_model_training
```

Other new learning authorities resolve from policy defaults / tenant rights profile /
agreement / data class / source class / legal restrictions.

## 3.4 DisclosureAuthority

```yaml
disclosure_authority:
  tenant_internal: true
  olympus_internal: true
  cross_tenant_identifiable: false
  external_identifiable: false
  generalized_cross_tenant: true
  generalized_external: governed
```

## 3.5 RetentionAuthority / TerminationAuthority

```yaml
retention_authority:
  # composes: Applicable Law + Legal Hold + Agreement + DataRightsGrant +
  # Event Retention Class + Resource Storage Policy + Tenant Configuration +
  # Artifact Derivation Class = Effective Retention Decision (deterministic precedence)

termination_authority:
  contributed_source_data: delete_by_policy
  tenant_identifiable_derived_data: recompute_or_delete
  tenant_exports: tenant_retains
  audit_records: retain_as_required
  generalized_derivatives: retain_if_independently_qualified
  model_weights: retain_if_non_reconstructable_and_permitted
  benchmarks: retain_if_generalization_passed
  ontology_improvements: retain
  security_fraud_signatures: governed_retention
```

Termination is a **rights-aware lifecycle event**, not a universal hard delete.

## 3.6 Intelligence Rights Profile (policy preset; never different code paths)

| Profile | Olympus generated-output retention | Generalized learning | Olympus internal intelligence | Contributed training |
|---|---:|---:|---:|---:|
| Sovereign | Minimal | No | No | No |
| Private | Required operations only | No or limited | No | No |
| Standard | Yes | Yes | Yes, bounded | No |
| Collaborative | Yes | Yes | Yes | Explicitly governed |

---

# 4. Effective Rights Resolver (canonical rights decision authority)

```text
resolve_effective_rights(tenant, source, artifact, actor, requested_use, purpose, destination, as_of)
```

Inputs: `DataRightsGrant`, `ConsentPolicyDecision`, Intelligence Rights Profile,
agreement/MSA policy, source contract, data sensitivity, semantic class, derivation class,
legal hold, retention policy, data residency, actor role, requested purpose, destination,
temporal effective date.

```yaml
RightsDecision:
  decision_id: rdec_...
  allowed: bool
  disposition: str
  reason_codes: [str]
  source_grant_refs: [str]
  consent_decision_refs: [str]
  ownership_class: str
  permitted_uses: [str]
  permitted_derivations: [str]
  permitted_learning: [str]
  permitted_disclosures: [str]
  retention: str
  deletion: str
  survival: str
  evaluated_at: str
  effective_as_of: str
  policy_version: str
  evidence_refs: [str]
```

Every material authorization produces a **durable, immutable, versioned, temporally
effective, tenant-scoped, evidence-linked, reproducible** decision record
(`rights_decisions` store). Material actions include: store; normalize; create graph
mutation; create derived intelligence; export; disclose; train; benchmark; generalize;
enter Olympus graph; Olympus internal query; retain after tenant termination.

Decision identity reproducible from: tenant + actor + purpose + artifact + requested_use +
destination + governing source/grant + subject reference + policy version + as-of time
(decision idempotency, §17). Live requests re-evaluate current grant and consent state;
only an explicit immutable `as_of` request may replay a historical decision snapshot.

---

# 5. Rights derivation taxonomy (independent of epistemic trust class)

Rights derivation classes (do NOT merge with existing trust classes):

```text
SOURCE_REPRESENTATION
NORMALIZED
TENANT_IDENTIFIABLE_DERIVATIVE
AETHER_GENERATED_INTELLIGENCE
AGGREGATED
GENERALIZED
MODEL_DERIVED
PLATFORM_KNOWLEDGE
```

An artifact may be `trustClass = INFERRED`, `semanticLevel = C`,
`rightsDerivation = AETHER_GENERATED_INTELLIGENCE` — dimensions remain independent.

## 5.1 Aether Generated Intelligence envelope

```yaml
GeneratedIntelligenceEnvelope:
  intelligence_id: str
  tenant_id: str
  semantic_level: C
  epistemic_status: str
  evidence_refs: [str]
  computation_ref: str
  model_refs: [str]
  source_rights_refs: [str]
  rights_derivation: AETHER_GENERATED_INTELLIGENCE
  generated_output_rights_ref: str
  created_at: str
  as_of: str
```

At minimum, classify: identity resolution, profile inference, relationship inference,
relationship fidelity, social propagation, risk vectors, risk assessments, fraud
hypotheses, journey reconstruction, episode creation, attribution, outcome inference,
anomaly detection, value projections, recommendations, investigation findings, behavioral
predictions, model-generated classifications, generalized graph features.

## 5.2 RightsLineage

```yaml
RightsLineage:
  artifact_id: str
  parent_artifact_refs: [str]
  source_grant_refs: [str]
  rights_decision_refs: [str]
  derivation_class: str
  semantic_level: str
  trust_class: str
  computation_ref: Optional[str]
  model_refs: [str]
  generated_output_rights_ref: Optional[str]
  effective_rights_decision_ref: Optional[str]
```

Reuse canonical lineage/evidence references; no duplicate evidence system.

---

# 6. Generalization Gateway (runtime adapter owned by `rights_irrl`, not a parallel graph)

```yaml
GeneralizationRequest:
  artifact_ref: str
  tenant_id: str
  requested_destination: olympus_graph | platform_learning | benchmark | model_training
  requested_use: str
  evidence_refs: [str]
  rights_refs: [str]
  actor: str
  purpose: str
```

Checks: active DataRightsGrant; ConsentPolicyDecision; learning authority; Olympus-baseline
authority; disclosure policy; data sensitivity; PII presence; tenant-identifiability;
minimum population threshold; outlier/re-identification risk; source-license restrictions;
residency restrictions; contractual restrictions; revocation state; lineage completeness;
semantic derivation class.

Transformations (all registered + evidence-linked): PII stripping; tenant identifier
removal; tenant metadata stripping; subject pseudonymization; bucketing; cohort
thresholding; k-anonymity-like minimum population controls; distribution aggregation;
outlier suppression; edge abstraction; feature coarsening; temporal coarsening; geographic
coarsening; sensitivity reduction.

```yaml
GeneralizedArtifact:
  generalized_artifact_id: str
  parent_artifact_refs: [str]
  transformation_refs: [str]
  generalization_policy_version: str
  rights_decision_ref: str
  source_grant_refs: [str]
  tenant_identifiable: false
  reidentification_risk: str
  minimum_population_met: bool
  lineage_ref: str
  permitted_destinations: [str]
  retention_policy_ref: str
```

Only qualifying outputs may enter generalized Olympus knowledge.

---

# 7. Olympus Internal Intelligence (first-class actor + purpose, NO global superuser)

Actor/principal: `OLYMPUS_INTERNAL`. Purposes:

```text
PLATFORM_RESEARCH
MODEL_IMPROVEMENT
SECURITY_RESEARCH
FRAUD_RESEARCH
RESOLVER_CALIBRATION
ONTOLOGY_RESEARCH
PRODUCT_ANALYTICS
BENCHMARK_ANALYSIS
SUPPORT_INVESTIGATION
INCIDENT_RESPONSE
```

Query flow: `actor + purpose + scope → Effective Rights Resolver (authorized sources,
tenants, data classes, disclosure class) → purpose-filtered Graph-of-Graphs query →
RightsDecision + audit evidence`. No `olympus_superuser = true`.

Kyber intelligence requests carry:

```yaml
KyberIntelligenceRequest:
  operator_id: str
  role: str
  purpose: str
  requested_tenants: [str]
  requested_scope: str
  requested_data_classes: [str]
  requested_actions: [str]
```

Backend resolves authority; frontend never determines rights. Prohibited:
unrestricted operator browsing of all-tenant raw records.

---

# 8. Learning & model governance

Gates: TRAINING, EVALUATION, FINE-TUNING, EMBEDDING INDEX CREATION, FEATURE GENERATION,
BENCHMARK GENERATION, REINFORCEMENT/CALIBRATION — all resolve rights before use.

```yaml
TrainingDataManifest:
  run_id: str
  model_ref: str
  dataset_artifact_refs: [str]
  rights_decision_refs: [str]
  grant_refs: [str]
  learning_authority_classes: [str]
  exclusion_count: int
  transformation_refs: [str]
  temporal_snapshot: str
  policy_version: str
```

Distinguish `TENANT_LOCAL` vs `GENERALIZED_PLATFORM` learning at storage and
model-registry level. Revocation states:

```text
NO_ACTION_REQUIRED
RETRAIN_REQUIRED
MODEL_QUARANTINE_REQUIRED
EVALUATION_REQUIRED
LEGAL_REVIEW_REQUIRED
BLOCKED
```

Never claim a model was "deleted" merely because training rows disappeared.

---

# 9. Retention resolution (no separate retention platform)

Deterministic precedence:
1. Legal prohibition / mandatory deletion
2. Legal hold / preservation obligation
3. Contract-specific explicit rule
4. Source-license rule
5. DataRightsGrant rule
6. Tenant rights profile
7. Canonical event retention class
8. Storage policy
9. Platform default

Lifecycle actions:

```text
PRESERVE DELETE HARD_DELETE TOMBSTONE QUARANTINE SUPPRESS INVALIDATE RECOMPUTE RETRAIN ANONYMIZE GENERALIZE LEGAL_HOLD
```

Deletion cascade is dependency-aware (raw object, normalized row, graph edge, vector
embedding, cached result, derived profile attribute, exported artifact, model-training
input → each dependent component receives its appropriate action). Generalized derivative
survival is conditional (rights permit + passed gateway + non-identifiable + license
permits + no legal deletion + lineage available + not a practical reconstruction).

---

# 10. Rights impacts & remediation

Revocation must: (1) deny future governed use immediately; (2) produce an impact graph
Grant→Observations→Normalized Facts→Graph State→Computed Intelligence→Exports/Models/
Generalized Artifacts; (3) mark affected material; (4) enqueue required remediation;
(5) preserve audit history; (6) re-evaluate generalized derivatives; (7) assess model
impact; (8) surface unresolved remediation in Kyber; (9) keep DSR/termination pending until
adapters report completion. No fake completion.

Rights-impact integration with Reconciled Control: IRRL answers "is the operation
authorized?"; Reconciled Control answers "how is an authorized operational change safely
executed?" (ChangeSet → approve → execute → verify → rollback/complete). No authority
collapse.

---

# 11. Propagation & envelope refs

- `SpineEnvelope.rights_decision_ref` transitions `@unpopulated → optional during migration
  → required on governed material interactions`. No consumer invents rights independently.
- `UniversalObservationEnvelope` carries lightweight rights refs (not the full decision):

```yaml
rights:
  grant_refs: [str]
  rights_decision_ref: str
  rights_policy_version: irrl-2
  rights_profile: standard
  evaluated_at: str
```

- Graph mutation `MutationIntent`/`MutationRecord` gain a rights ref; every material
  derivative resolves to the rights of its upstream evidence.
- Identity revision integration: rights lineage carries `entity_ref`, `identity_revision`,
  `identity_watermark`; merge/split triggers rights impact evaluation.
- Temporal rights: `valid_from/valid_to/system_recorded_at/evaluated_as_of/policy_version`;
  historical replay uses historically valid rights (`ORIGINAL_RIGHTS` vs
  `CURRENT_RIGHTS_RESTATEMENT` are different operations).
- Data Exchange: every `DataArtifact` carries `artifact_rights` (rights_decision_ref,
  source_grant_refs, owner_class, export_authority, retention_authority, deletion_authority,
  rights_derivation_class). Downloads enforce current authorization; artifact existence ≠
  download authority. Exports may carry a machine-readable rights manifest.

---

# 12. Projection & exploration rights

A 360 projection does not become canonical ownership source merely by rendering data.
Projection output carries `RightsContext`:

```yaml
RightsContext:
  availability: str
  restrictions: [str]
  source_rights_refs: [str]
  effective_decision_ref: str
  exportable: bool
  suppressions: [str]
  limitations: [str]
```

Projections never upgrade rights. Exploration fabric evaluates rights before loading data,
composing lenses, cross-scope pivots, saving operations, exporting results. Pivots cannot
silently expand authority; denial = typed suppression.

---

# 13. No-parallel-registries rule (Phase 0 validator)

Explicitly prohibited file names (duplicate data-authority ledgers):

```text
irrl-registry.json
ownership-registry.json
learning-rights-registry.json
retention-rights-registry.json
generalization-rights-registry.json
```

unless they are true canonical vocabularies registered under the Contract Spine. Policy data
remains in its owning canonical authorities. (Id-level analogue already enforced by
`parallel_id_collision` in `scripts/lib/spine_registry_validation.py`.)

Prohibited runtime shortcuts (fail CI if new code):
- writes tenant material to Olympus graph without IRRL authorization;
- trains models without learning-authority evidence;
- creates generalized artifacts without Generalization Gateway evidence;
- exports governed material without current export authority;
- performs Olympus-internal multi-tenant queries without purpose-bound authority;
- converts missing rights into permissive defaults;
- creates a duplicate rights registry;
- treats tenant ownership as equivalent to every downstream right;
- treats Olympus ownership as equivalent to unrestricted disclosure.

---

# 14. Spine registry target

`rights_irrl` row must reflect concrete implementation:

- **Authority declaration:** Authoritatively resolves rights over data use, retention,
  output derivation, learning, model-training eligibility, generalization, Olympus internal
  intelligence, disclosure, portability, and termination by composing existing consent,
  data-rights, lifecycle, lineage, and storage authorities.
- **Non-ownership declaration:** Does not own consent-purpose state, source facts, graph
  facts, identity, model state, or storage objects. It authorizes operations over those
  authorities and records the governing RightsDecision.
- **Published ports:** `rights_decision_ref`, `effective_rights`, `output_rights`,
  `learning_authority`, `retention_decision`, `generalization_decision`,
  `olympus_internal_authority`, `rights_lineage`, `rights_impact`.
- **Consumed ports:** `consent_decision`, `data_rights_grant`, `evidence_ref`, `lineage_ref`,
  `identity_watermark`, `temporal_watermark`, `storage_policy`, `retention_policy`,
  `agreement_ref`, `model_ref`, `artifact_ref`.
- Expected logical dependency: `contract_spine → rights_irrl → ingestion, evidence, graph,
  model_governance, projection_plane, exploration, data_exchange, tenant_readiness, kyber`.

---

# 15. Storage additions

`rights_decisions` (durable decision record), `rights_lineage` (artifact→parent rights
linkage where not representable in existing lineage), `rights_impacts` (revocation/deletion/
restatement impact state), `training_data_manifests` (model governance), `generalized_artifacts`
(only if existing `data_artifacts` substrate cannot represent generalized logical artifacts —
prefer reusing `data_artifacts`). No redundant stores.

---

# 16. Migration strategy

- **M0 Compatibility:** existing booleans authoritative; new structured rights shadow-derived;
  no broader rights automatically.
- **M1 Dual representation:** new contracts persist alongside booleans; parity checks require
  semantically equivalent decisions for legacy-supported actions.
- **M2 Canonical resolver:** all new features call `EffectiveRightsResolver`; legacy helpers
  delegate.
- **M3 Legacy field deprecation:** booleans serialized for compatibility, no longer
  independently evaluated.
- **M4 Removal:** remove legacy policy evaluation only after callers migrated, no SDK/API
  dependency, migrations complete, replay green, release evidence complete.

Rollout modes per gate: `OFF | SHADOW | WARN | ENFORCE`. No global hard flip. Initial
migration = existing rights helpers + new resolver SHADOW → compare decisions → resolve
mismatches → WARN → ENFORCE.

---

# 17. Implementation program (phases)

**Phase 0 — Reconciliation & governing doctrine:** publish blueprint in-repo; supersede
standalone-IRRL topology in `IRRL_NAMING_OVERLAY.md`; update `rights_irrl` spine row; define
canonical rights taxonomy + output-rights doctrine + Intelligence Rights Profile vocabulary;
register ownership map/co-move requirements; add architecture validator preventing parallel
rights registries. Exit: repo describes one rights authority topology; no doc claims IRRL is
a standalone runtime; `make ci-check` green.

**Phase 1 — Canonical rights contract expansion:** extend `DataRightsGrant` with nested
`SourceUseAuthority`, `GeneratedOutputRights`, `LearningAuthority`, `DisclosureAuthority`,
`TerminationAuthority` (+ `RetentionAuthority`); compatibility adapters; TS twin; schema/
parity tests. Constraints: legacy rights do not broaden; unknown new fields fail closed;
raw-model-training rights remain explicit.

**Phase 2 — Effective Rights Resolver:** canonical resolver; `RightsDecision` persistence;
policy precedence; temporal effective-dating; actor/purpose/destination evaluation; signed/
auditable evidence. Integrates DataRightsService, ConsentPolicyEngine, retention, agreements,
source/license classification, tenant rights profile. Exit: all legacy checks representable
through resolver decisions.

**Phase 3 — Rights propagation:** populate `SpineEnvelope.rights_decision_ref`; observation
rights refs; Bronze rights metadata; normalization preservation; Silver propagation; graph
mutation preservation; evidence lineage. Invariant: no governed derivative loses rights
ancestry.

**Phase 4 — Aether Generated Intelligence:** generated-intelligence envelope; rights
derivation taxonomy; computation-rights integration; model-reference integration;
output-rights stamping. First integrations: identity, relationship, risk, fraud, outcome,
episode, journey, attribution, profile, recommendation.

**Phase 5 — Projection & Exploration rights:** `RightsContext` on projection/exploration
outputs; suppression, unavailable, export restricted, generalized-only, tenant-local,
operator-only. Exit: no 360/Exploration path bypasses rights evaluation.

**Phase 6 — Generalization Gateway:** eligibility evaluator; transformation registry;
subject/tenant stripping; aggregate thresholds; re-identification risk; lineage; generalized
artifact output; Olympus Graph write adapter through canonical gateway. Exit: no
tenant-derived intelligence enters Olympus generalized knowledge except through the gateway.

**Phase 7 — Learning & model governance:** integrate training/evaluation/embeddings/resolver
calibration/ontology/schema mapping/benchmarks; `TrainingDataManifest`; rights eligibility
report; revocation/model impact.

**Phase 8 — Retention, deletion & restatement:** unify effective lifecycle resolution over
DataRetentionPolicy, event retention, storage policy, legal hold, rights grant, artifact
type, tenant profile; impact/recompute adapters for graph/search/vectors/caches/models/
exports/generalized artifacts.

**Phase 9 — Olympus internal intelligence:** Olympus internal actor; purpose vocabulary;
purpose-bound internal authorization; Graph-of-Graphs filtering; internal query audit; Kyber
operator views. Exit: no unrestricted internal all-tenant access outside explicit authorized
purposes.

**Phase 10 — Tenant product surface:** Data & Intelligence Rights settings; activation
profile; grant status; generated-output explanation; learning controls where configurable;
deletion/revocation state; export/portability status. Activation cannot claim "ready" if
required agreement/profile/source-rights/consent missing — rights become part of readiness.

**Phase 11 — Kyber rights operations:** Kyber surfaces for rights decisions, impact, blocked
operations, generalized artifacts, model eligibility, retraining impact, Olympus-internal
access, remediation. Read/write executes through owning authorities.

**Phase 12 — Legal/product/runtime parity:** parity matrix across MSA term, DPA term, privacy
term, product label, rights profile field, DataRightsGrant field, runtime check, tenant UI,
Kyber UI. No public/contractual term materially unimplemented.

**Phase 13 — Conformance closure:** close all 14 Spine P0 conformance items for `rights_irrl`
(authority/non-ownership; canonical contracts; ports/adapters; dependency DAG; typed
degradation; temporal behavior; evidence/restatement; tenant/consent/rights/retention/
residency/export; graph mutation policy; API/event/UI/Kyber; readiness/entitlement; security/
compliance/observability; migration/recompute/rollback; positive/negative/replay/isolation/
golden tests). Then `in_flight → implemented`, then `canonical` only after operational
evidence. Verification domain additions must invoke contract parity, resolver tests, negative
authorization, tenant isolation, replay, historical-rights tests, DSR, retention, output-rights
propagation, learning eligibility, model manifest, Graph-of-Graphs isolation, generalization,
Kyber purpose checks, Data Exchange export checks.

---

# 18. Golden scenarios (minimum journeys)

- **A — Standard Tenant:** commerce data → store/resolve/derive/outcome intelligence → tenant
  views and exports; generalized non-identifying learnings enter Olympus knowledge; raw
  contributed data does not.
- **B — Sovereign Tenant:** service-required use only; tenant-local processing + results; no
  generalized learning; no Olympus internal analysis beyond support/security permissions; no
  model contribution.
- **C — Collaborative Tenant:** explicit generalized learning + broader benchmarking +
  contributed model training; training manifest shows qualifying inputs + rights decisions.
- **D — Revocation:** revoke generalized-learning → block new generalization immediately,
  identify affected generalized artifacts, determine retain/delete/recompute, assess model
  impact, surface remediation.
- **E — Termination:** distinguish contributed-data deletion, tenant-identifiable derivatives,
  exported outputs, audit records, generalized derivatives, model contributions, legal holds.
- **F — Olympus internal intelligence:** operator cross-tenant generalized analysis requires
  Olympus actor + valid purpose + authorized data classes + permitted generalized material +
  auditable decision; raw tenant material inaccessible where unauthorized.

---

# 19. Metrics & alerts

Metrics: `rights_decisions_total`, `rights_denials_total`, `rights_shadow_mismatch_total`,
`rights_unknown_total`, `rights_expired_grant_total`, `rights_revoked_grant_total`,
`generalization_requests_total`, `generalization_allowed_total`, `generalization_denied_total`,
`generalization_reidentification_block_total`, `generated_intelligence_total`,
`learning_eligibility_total`, `training_rights_exclusion_total`,
`olympus_internal_queries_total`, `olympus_internal_query_denials_total`,
`rights_remediation_pending`, `rights_recompute_pending`, `rights_retraining_pending`.
Never convert unknowns into zeros.

Alert on: unauthorized attempted write; generalization-gateway denial with
re-identification block; rights shadow mismatch; unknown rights resolution; training without
a manifest; Olympus-internal query denial; stale remediation. Alerts must cite the durable
decision/impact id, never silently drop.
