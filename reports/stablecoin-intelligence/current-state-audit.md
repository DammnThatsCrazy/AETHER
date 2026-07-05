# Stablecoin Intelligence Current-State Audit

Date: 2026-07-05
Branch scope: PR1 foundation audit and hardening.

## Findings

- Existing x402 systems are observation-oriented in `services/x402`, shared lifecycle events, and agentic observability repositories. Production documentation must continue to state that settlements are external observations, not Aether-executed transfers.
- Existing economic repositories include payment intents and settlement events. Payment intents model lifecycle state and must not be counted as finalized stablecoin settlement without onchain or facilitator evidence.
- Existing data lake repositories already implement Bronze, Silver, and Gold concepts with provenance and quarantine gates, but generic Gold identity was only metric/entity/type and is unsafe for stablecoin metrics. PR1 adds stablecoin-specific versioned Gold identity.
- Existing Dune repositories are tenant-scoped by `tenant_scope` for query, promotion, and rollback. Stablecoin ingestion must continue to require execution identity and prohibit direct graph mutation.
- Existing deployment/asset registry files are generic chain/protocol data. No canonical stablecoin deployment registry was found before this PR.
- Existing Profile360, graph, campaign, journey, Kyber, billing, and entitlement systems exist, but stablecoin-specific routes and surfaces are deferred behind off-by-default flags until PR2-PR4.

## Risks corrected in PR1

- Added canonical stablecoin asset/deployment/observation/finality/support taxonomies.
- Added decimal-safe stablecoin money helper that rejects unlike raw token additions.
- Added platform deployment registry entries that distinguish USDC Ethereum and USDC Base deployments.
- Added durable stablecoin repositories and additive migration for deployments, observations, support assertions, reconciliation, and Gold metrics.
- Added Gold identity that includes tenant, metric version, asset, deployment, chain, window, dimensions, and source.
- Added tests covering mixed-asset rejection, deployment separation, tenant/execution identity, Gold collision safety, Dune repeated execution distinction, and Bronze quarantine blocking Silver.

## Release blockers for later PRs

- Provider ingestion, finality tracking, reconciliation engines, Gold materialization jobs, graph projection, Profile360 composers, Aether UI, Kyber operations, Olympus benchmarks, alerts, webhooks, exports, metering, and staging validation remain intentionally disabled/deferred after PR1.
- Missing tenant IDs must remain rejected or quarantined for tenant-owned financial rows.
- Documentation must not claim production readiness until PR4 evidence exists.
