---
title: Rights Taxonomy — Aether Canonical Rights Vocabulary
slug: architecture/rights-taxonomy
section: architecture
visibility: I
audience: [architect, dev-senior, compliance]
status: experimental
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 3
---

# Rights Taxonomy — Aether Canonical Rights Vocabulary

This file is the **companion vocabulary reference** for the in-repo, frozen
Rights Authority blueprint
([RIGHTS_AUTHORITY_BLUEPRINT.md](./RIGHTS_AUTHORITY_BLUEPRINT.md)): it defines
the four-class information taxonomy and indexes the canonical vocabulary to its
declared code homes. It is **not** a registry and adds no parallel rights
authority — every term below is owned by the grant/consent/retention machinery
and (where noted) the implementing canonical extension being built per the
blueprint. Where a symbol is marked **planned/implementing**, the token set is
the declared canonical vocabulary per the blueprint and its exact model form is
defined by the implementing code this session; nothing here claims runtime
enforcement that is not yet wired.

## 1. The four information classes

Ownership/authority must **never** be encoded as one `owner` field with all
downstream permissions inferred. For every governed artifact the platform
resolves ownership, use, retention, derivation, learning, disclosure,
commercialization, portability, deletion, and survival independently (see
Separate authorities). The primary classification of information into four
classes (blueprint §2) governs those resolutions:

| Class | Definition | Examples |
|---|---|---|
| **Class I — Contributed Information** | Originates outside Aether; property interest normally remains with the tenant / data subject / source provider / contractual licensor; Aether receives governed use rights | SDK observations, tenant imports, CRM data, payment info, provider data, tenant-owned identity, webhooks, campaign info |
| **Class II — Canonicalized Information** | Operationally transformed without substantial new intelligence; source rights continue to govern; transformation does not create an Olympus-exclusive asset | Normalized records, schema-converted events, canonical timestamps, currency normalization, resolved provider IDs, normalized geo refs, canonical asset IDs |
| **Class III — Aether Generated Intelligence** | Produced through meaningful Aether computation; **commercial default** is Olympus retains proprietary rights in the Aether-created computational artifact while the tenant receives broad governed use rights for its business; never treated as equivalent to raw tenant data | Identity resolution, clusters, relationship fidelity, risk assessments, fraud hypotheses, attribution, outcomes, journeys, inferred episodes, predictions, recommendations, findings, anomaly classifications, value projections, generalized patterns, graph-derived features, model-derived classifications |
| **Class IV — Generalized Aether Knowledge** | An Aether-generated artifact that passed the **Generalization Gateway** and no longer exposes prohibited tenant-identifiable / tenant-confidential information; may become durable Olympus intellectual capital where rights permit | Generalized fraud patterns, behavioral motifs, ontology improvements, resolver calibration, aggregate benchmarks, non-identifying feature distributions, generalized graph patterns, population trends, schema mappings, model improvements, protocol classification |

Two doctrine notes from the blueprint that shape the classes:
commercial doctrine (§1.2) — tenant ownership of contributed information does not
automatically create ownership of every intelligence artifact Aether generates;
trust doctrine (§1.3) — Olympus proprietary rights over Aether-generated
intelligence do not create unrestricted authority to expose tenant-identifiable
or tenant-confidential information to another tenant or external party.

## 2. Separate authorities

For each governed artifact these are resolved independently (blueprint §1.1):

`OWNERSHIP` · `USE AUTHORITY` · `RETENTION AUTHORITY` ·
`DERIVATION AUTHORITY` · `LEARNING AUTHORITY` · `DISCLOSURE AUTHORITY` ·
`COMMERCIALIZATION AUTHORITY` · `PORTABILITY AUTHORITY` · `DELETION AUTHORITY` ·
`SURVIVAL AUTHORITY`.

In the structured contract these are carried by the nested `DataRightsGrant`
components — `SourceUseAuthority` (use), `GeneratedOutputRights` (ownership of
generated output + commercialization + survival), `LearningAuthority` (learning),
`DisclosureAuthority` (disclosure), `RetentionAuthority` (retention),
`TerminationAuthority` (deletion/survival at termination) — composed by the
Effective Rights Resolver into each `RightsDecision` (blueprint §3–§5).

Consent grants carry an explicit `subject_ref` for receipt lookup; the
`consent_basis` field remains legal/purpose metadata. A missing or mismatched
subject receipt is a denial, and live resolution rechecks current consent and
grant status rather than replaying a prior decision. An `as_of` request is the
explicit boundary for replaying an immutable historical decision.

## 3. Rights-derivation classes

The rights-derivation taxonomy is **independent of the epistemic trust classes**
(blueprint §5). An artifact may be `trustClass = INFERRED`,
`semanticLevel = C`, `rightsDerivation = AETHER_GENERATED_INTELLIGENCE` — the
dimensions never merge.

`SOURCE_REPRESENTATION` · `NORMALIZED` · `TENANT_IDENTIFIABLE_DERIVATIVE` ·
`AETHER_GENERATED_INTELLIGENCE` · `AGGREGATED` · `GENERALIZED` ·
`MODEL_DERIVED` · `PLATFORM_KNOWLEDGE`.

## 4. Canonical vocabulary reference

Declared code homes: the python models of the structured contracts / canonical
package (`Backend Architecture/aether-backend/services/integrations/data_rights/models.py`
for grant components and
`Backend Architecture/aether-backend/services/rights_authority/` for the
resolver/enum surface), with the TS twin
`packages/shared/data-rights.ts`. These are the **planned / implementing**
homes per the blueprint (this session); the current enforced surface remains the
legacy `DataRightsGrant` booleans and `DataRightsService` fail-closed checks.

| Canonical enum | Members (blueprint) | One-line meaning |
|---|---|---|
| `RightsDerivationClass` | `SOURCE_REPRESENTATION`, `NORMALIZED`, `TENANT_IDENTIFIABLE_DERIVATIVE`, `AETHER_GENERATED_INTELLIGENCE`, `AGGREGATED`, `GENERALIZED`, `MODEL_DERIVED`, `PLATFORM_KNOWLEDGE` (§5) | Derivation dimension of a governed artifact, independent of trust/semantic class |
| `LearningClass` | `INFERENCE`, `TENANT_ADAPTATION`, `GENERALIZED_LEARNING`, `RESOLVER_CALIBRATION`, `ONTOLOGY_LEARNING`, `SCHEMA_MAPPING_LEARNING`, `BENCHMARKING`, `CONTRIBUTED_MODEL_TRAINING`, `OLYMPUS_INTERNAL_INTELLIGENCE` (§3.3) | The governed learning activities; legacy `model_training_allowed` maps **only** to `contributed_model_training` and never broadens |
| `OwnershipClass` | Value set declared by the implementing models (blueprint §4 `RightsDecision.ownership_class`) | Ownership dimension resolved per artifact — never inferred from a single `owner` field or from tenant ownership of contributed source data |
| `IntelligenceRightsProfile` | `Sovereign`, `Private`, `Standard`, `Collaborative` (§3.6) | Policy preset over generated-output retention, generalized learning, Olympus internal intelligence, and contributed training; never a different code path |
| `DisclosureBoundary` | Value set declared by the implementing models (blueprint §3.4 disclosure fields) | Boundary a disclosure is evaluated against: tenant-internal / Olympus-internal / cross-tenant-identifiable / external-identifiable / generalized-cross-tenant / generalized-external |
| `OlympusPurpose` | `PLATFORM_RESEARCH`, `MODEL_IMPROVEMENT`, `SECURITY_RESEARCH`, `FRAUD_RESEARCH`, `RESOLVER_CALIBRATION`, `ONTOLOGY_RESEARCH`, `PRODUCT_ANALYTICS`, `BENCHMARK_ANALYSIS`, `SUPPORT_INVESTIGATION`, `INCIDENT_RESPONSE` (§7) | Purpose vocabulary for the `OLYMPUS_INTERNAL` actor; no global superuser — internal queries are purpose-bound and audited |
| `LifecycleAction` | `PRESERVE`, `DELETE`, `HARD_DELETE`, `TOMBSTONE`, `QUARANTINE`, `SUPPRESS`, `INVALIDATE`, `RECOMPUTE`, `RETRAIN`, `ANONYMIZE`, `GENERALIZE`, `LEGAL_HOLD` (§9) | Typed lifecycle action assigned per dependent component in the deletion/termination cascade |
| `ModelRevocationState` | `NO_ACTION_REQUIRED`, `RETRAIN_REQUIRED`, `MODEL_QUARANTINE_REQUIRED`, `EVALUATION_REQUIRED`, `LEGAL_REVIEW_REQUIRED`, `BLOCKED` (§8) | Post-revocation model impact state; a model is never claimed "deleted" merely because training rows disappeared |
| `RightsDecisionDisposition` | Value set declared by the implementing models (blueprint §4 `RightsDecision.disposition` + `reason_codes`) | Typed outcome disposition of an Effective Rights Resolver `RightsDecision` (`rdec_*`), carrying reasons, source-grant refs, and consent refs |

Structured contract components referenced by the above — `SourceUseAuthority`,
`GeneratedOutputRights`, `LearningAuthority`, `DisclosureAuthority`,
`RetentionAuthority`, `TerminationAuthority` — nest onto `DataRightsGrant`
(blueprint §3) and are detailed in
[DATA_RIGHTS_LEDGER.md](./DATA_RIGHTS_LEDGER.md).

Related: [RIGHTS_AUTHORITY_BLUEPRINT.md](./RIGHTS_AUTHORITY_BLUEPRINT.md)
(canonical implementation contract — this file does not replace it),
[DATA_RIGHTS_LEDGER.md](./DATA_RIGHTS_LEDGER.md) (grant ledger + structured
contract surface),
[IRRL_NAMING_OVERLAY.md](./IRRL_NAMING_OVERLAY.md) (naming overlay / label map
for the `rights_irrl` spine).
