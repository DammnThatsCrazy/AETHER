---
title: High-Cardinality Agent Lineage
slug: architecture/high-cardinality-agent-lineage
section: architecture
visibility: I
audience: [architect, dev-senior, ops, security]
status: experimental
since_version: 0.1.0-alpha.0
source_files: [services/api/actions/agent_lineage/engine.py, services/api/actions/agent_lineage/service.py, services/api/actions/agent_lineage/repository.py, services/api/actions/agent_lineage/routes.py, services/api/intelligence/risk360/fanout.py, services/api/shared/agent_lineage/vocabulary.py, services/api/shared/agent_lineage/models.py, packages/shared/agent-lineage.ts]
canonical_owner: graph@aether
---

# High-Cardinality Agent Lineage

One human or organization may act through a handful of agents or through hundreds of
thousands of them. This design answers one question at any size: who caused,
authorized, operated, delegated, influenced or benefited from this machine activity,
and what evidence supports that? Measured results are in
[the scale proof ledger](../product/productization/agent-lineage-scale-proof-ledger.md).
That ledger is a measurement, not a production readiness claim.

## How much Aether knows versus how much a request returns

```text
Bronze evidence -> Silver execution facts -> resolution -> lineage read model
                -> aggregate, cluster, paginate -> bounded response
```

The 500-node and 2,000-edge graph budgets limit one response. They never limit what is
known. A principal with 74,281 agents is read through a summary, then clusters, then a
branch, then one agent. Three query modes follow from this: interactive pages inside
the budgets, pre-aggregated analytical reads, and full extraction as an asynchronous
export job.

## Where each thing lives

| Concern | Location |
|---|---|
| Vocabularies and wire models | `services/api/shared/agent_lineage/`, twin `packages/shared/agent-lineage.ts` |
| Observation contexts | `packages/shared/contracts/observation-envelope-registry.json` |
| Execution facts | `services/api/ingestion/silver/projectors/agent_execution_projector.py` |
| Bulk resolver | `services/api/actions/agent_lineage/engine.py` |
| Read model stores | `services/api/actions/agent_lineage/repository.py` |
| Reconcile and reads | `services/api/actions/agent_lineage/service.py`, `routes.py`, `jobs.py` |
| Fan-out analysis | `services/api/intelligence/risk360/fanout.py` |
| Surfaces | Profile360 and Agent360 panels in `apps/aether-web/src/features/agent360/`, Kyber `apps/kyber-web/src/pages/agent-lineage/` |

The tables are `principal_agent_lineage`, `principal_agent_lineage_summary`,
`principal_agent_lineage_clusters`, `agent_lineage_nodes`, `agent_lineage_restatements`,
`agent_lineage_tenant_state` and `agent_lineage_principal_bindings`. The first five are
derived: dropping them loses no evidence. Tenant state holds an erasure counter that
stops a worker reusing a fold read before an erasure. Bindings are tenant declarations,
which are inputs.

## Resolution

Facts fold into per-agent state in any order, and a replayed event id changes nothing.
`as_of` comes from the evidence rather than the clock, so rebuilding the same evidence
produces identical rows. Each `resolve()` pass then derives the following.

**Canonical parent.** Each agent keeps one parent: observed parents first, then
strongest evidence, earliest time and id. Competing parents mark the row `partial`.
With one parent per agent the topology is a functional graph, so traversal is iterative
and linear. Depth past the processed limit (64, never below the durable minimum of 32)
becomes `depth_limited` and truncates the summary's disclosure.

**Cycles.** Walking parent pointers finds each cycle once. It is cut at a deterministic
anchor, its members are marked `cyclic`, agents hanging below it are `partial`, and
anything inherited across it is capped at inferred. Cycles do not crash traversal,
inflate counts or hide members.

**Principal links.** A link is a principal, an evidence class and the authority it
rests on.

| Source | Evidence class | Attribution |
|---|---|---|
| Verified grant from a principal | `VERIFIED_AUTHORITY` | verified |
| Registered agent owner, deterministic binding | `DETERMINISTIC_BINDING` | verified |
| Attestation | `CRYPTOGRAPHICALLY_ATTESTED` | verified |
| Claim with a provider binding | `PROVIDER_ASSERTED` | inferred |
| Tenant declaration | `TENANT_DECLARED` | inferred |
| Shared deployment, gated on count and share | `INFRASTRUCTURE_CORRELATED` | suspected cluster |
| Reported claim with no binding | none | unresolved, under `unattributed` |

A link inherited down the tree is only as strong as its weakest hop. A parent reporting
a spawn from a verified deployment is a deterministic hop, and from an unverified one a
provider-asserted hop. An agent's own statement of its parent carries no attribution,
so an impostor naming a verified orchestrator as parent appears as an unresolved
candidate rather than a verified member of that fleet.

A non-proof link that a proof link contradicts is demoted to `unresolved`, not dropped,
and both rows list `competing_principal_ids`. Two weak claims both stay inferred. An
id named as a principal that is also observed as an agent is not attribution, which
keeps human and agent identities apart.

**Authority.** A grant's `delegation_allowed` and `maximum_delegation_depth` carry down
the chain. Descendants past them are `out_of_scope`, and revoked or expired authority
marks its whole branch. They stay in the projection, marked, because historical agents
must remain traceable.

**Clusters.** Fleets, swarms, execution, infrastructure and delegation clusters are
analytic groupings stating their `bases`. `implies_common_control` is true only when
every member is verified and no basis is weak. Without a principal, a group is a
`suspected_cluster`.

## Incremental maintenance and correction

Only changed agents and their descendants are re-derived. A property test folds the
same evidence in batches, including authority arriving mid-stream, and requires the
rows to equal a full rebuild. Authority records and bindings are versioned, so a stale
record cannot undo a correction. Restated rows are logged; past the log cap they are
counted, and the count is stored.

Roll-ups and clusters are recomputed tenant-wide on each pass, so reconcile in batches
rather than per event.

## Risk360

`fanout.py` turns neutral activity counts into the fan-out signal vocabulary. Only
behavior elevates a principal: authority failure rate, out-of-scope execution and
activity under revoked authority. Size, velocity, depth and tool volume are reported as
context and cannot move the level. Thresholds are uncalibrated heuristics, so signals
carry `score=None`. The six risk relationships (risky agent, risky cluster, delegated by
a risky actor, risky resource, resembling risky behavior, confirmed malicious) are
counted separately. Those the projection cannot support are `null`. Confirmed activity
only comes from an explicit adjudication input. Propagation is recorded per kind and
never becomes a finding about anyone downstream.

## Invariants and where they are enforced

| Invariant | Enforced by | Test |
|---|---|---|
| Human and agent never merge | `_own_links` | `test_a_human_and_an_agent_never_become_the_same_identity` |
| Scale alone never implies fraud | `_triggered` | `test_size_alone_with_no_behavioural_evidence_cannot_trigger` |
| A reported principal is a claim | `_own_links`, projector | `test_a_reported_principal_is_a_claim_until_a_binding_resolves_it` |
| A trace is not a run | `_apply`, projector | `test_a_trace_is_not_a_run` |
| Weak evidence never proves control | `attribution_for`, `_cluster` | `test_only_proof_classes_can_reach_verified` |
| Unknown never becomes zero | `_summary`, panels | `test_unknown_never_becomes_zero` |
| Truncation is disclosed | `Disclosure` | `test_recursion_is_iterative_and_deep_chains_degrade_explicitly` |
| Projection is rebuildable | `compare_rows`, service | `test_incremental_resolve_converges_on_a_full_rebuild` |
| Links retain evidence | `_row` | ground-truth fixture tests |
| No cross-tenant attribution | `ingest`, repositories | `test_tenants_are_isolated_on_read` |
| Corrections restate | `_log_restatement` | `test_a_correction_restates_downstream_rows_and_reversing_it_returns_the_same_state` |

## Known gaps

- Reconciliation needs a `job_schedules` row per tenant. No default schedule is seeded.
  An incremental pass misses facts with old timestamps until a periodic full rebuild.
- `delegated_by_risky_actor`, `interacted_with_risky_resource`, `resembles_risky_behavior`,
  `identity_churn` and `coordinated_execution_score` have no input yet and report `null`.
- `RiskEvidenceBundle.agent_lineage_fanout` is caller-supplied and no caller populates
  it yet. The `/risk` route reads the assessment directly.
- A source ref bound to different canonical agents in two namespaces stays a source ref.
