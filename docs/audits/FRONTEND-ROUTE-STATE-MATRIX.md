---
title: Frontend route-state coverage matrix
slug: audits/frontend-route-state-matrix
section: architecture
visibility: I
audience: [dev-senior, architect, ops]
status: experimental
since_version: "8.12.0"
---

# Frontend route-state coverage matrix

This matrix is the release ledger for frontend data truth. `A` means an
automated assertion exists, `I` means the behavior is implemented but not
asserted, `—` is a gap, and `n/a` is not applicable. The columns are loading
(`L`), successful empty (`E`), error/unavailable (`R`), populated (`P`), and
permission/capability gating (`G`). A failed request never counts as empty.

## Aether

| Route | Primary API dependencies | Critical | L | E | R | P | G | Current test evidence |
|---|---|---:|:---:|:---:|:---:|:---:|:---:|---|
| `/users` | entities and profile summaries | yes | I | A | A | — | I | parameterized route-state family |
| `/users/:id` | Profile360, identity, graph, trust, risk | yes | I | A | A | — | I | parameterized route-state family |
| `/users/:profileId/journey` | profile-scoped journey and campaign evidence | yes | I | A | A | — | I | parameterized route-state family |
| `/campaigns` | campaigns and attribution | yes | I | A | A | — | I | parameterized route-state family |
| `/campaigns/:id` | campaign detail and touchpoints | yes | I | A | A | — | I | parameterized route-state family |
| `/campaign-intelligence` | campaigns and attribution | yes | I | A | A | — | I | parameterized route-state family |
| `/campaign-intelligence/registry` | campaign registry | no | I | A | A | — | I | parameterized route-state family |
| `/campaign-intelligence/sources` | campaign sources | no | I | A | A | — | I | parameterized route-state family |
| `/campaign-intelligence/mapping-review` | mapping review | no | I | A | A | — | I | parameterized route-state family |
| `/campaign-intelligence/quality` | campaign quality | no | I | A | A | — | I | parameterized route-state family |
| `/campaign-intelligence/campaigns/new` | campaign create and validation | no | I | n/a | — | — | I | gap |
| `/graph` | graph summary, paths, clusters | yes | I | A | A | — | I | parameterized route-state family |
| `/compare` | comparison definitions, runs, preflight, findings | no | I | A | I | A | I | `comparison-page.test.tsx` |
| `/noesis` | Noesis conversations and answers | no | I | A | A | A | I | `noesis-page.test.tsx`, `noesis-workspace.test.tsx` |
| `/settings` | tenant profile, notifications, keys | yes | I | A | A | — | I | parameterized route-state family |
| `/settings/notifications` | notification preferences | yes | I | A | A | — | I | parameterized route-state family |
| `/onboarding` | readiness and blockers | no | I | A | A | — | I | parameterized route-state family |
| `/activation` | activation status, first value, plan/sdk/keys/test-event | yes | A | A | A | A | I | `activation-landing.test.tsx` (activation-page.tsx) |
| `/billing` | account, subscription, invoices | yes | I | A | A | — | I | parameterized route-state family |
| `/usage-plan` | measured usage and plan | yes | I | A | A | — | I | parameterized route-state family |
| `/me` | tenant profile and measured usage | no | A | A | A | A | I | `me-data-truth.test.tsx` |
| `/geo` | geographic summary | no | A | A | A | A | I | `geo-data-truth.test.tsx` |
| `/geo/:level/:geoId` | geographic drilldown | no | A | A | A | A | I | `geo-data-truth.test.tsx` |
| `/audit-exports` | audit export history | no | I | A | A | — | I | parameterized route-state family |
| `/value-review` | tenant value review | no | A | A | A | A | I | route-state family and `value-review-page.test.tsx` |
| `/security` | policy, audit, retention, DSR | no | I | A | A | — | I | parameterized route-state family |
| `/system-status` | tenant-safe health and incidents | yes | I | A | A | A | I | route-state family and `system-status-page.test.tsx` |
| `/data-quality` | quality summary and evidence | yes | I | A | A | A | I | route-state family and `data-quality-page.test.tsx` |
| `/integrations` | connector registry and connections | yes | I | A | A | A | I | route-state family and `connectors-page.test.tsx` |
| `/rewards` | reward decisions | no | I | A | A | — | I | parameterized route-state family |
| `/rewards/decisions` | reward decisions | no | I | A | A | — | I | parameterized route-state family |
| `/rewards/approval-queue` | reward approvals | no | I | A | A | — | I | parameterized route-state family |
| `/rewards/rails` | reward rail configuration | no | I | A | A | — | I | parameterized route-state family |
| `/rewards/campaigns/new` | reward campaign create | no | I | n/a | — | — | I | gap |
| `/suggestions` | targeting suggestions | no | I | A | A | A | I | `targeting-intelligence.test.tsx` |
| `/clusters/:clusterId` | cluster detail and impact | no | I | A | A | A | I | `targeting-intelligence.test.tsx` |
| `/delivery` | connector delivery history | no | I | A | A | — | I | parameterized route-state family |
| `/deployments` | external-agent deployments | yes | I | A | A | A | I | `deployments-page.test.tsx` |
| `/deployments/:id` | deployment health and activity | yes | I | A | A | — | I | parameterized route-state family |
| `/imports` | import sessions | yes | I | A | A | A | I | `imports-page.test.tsx` |
| `/imports/:id` | schema, mapping, validation, commit | yes | I | A | A | — | I | parameterized route-state family |
| `/payment-rails` | providers, sessions, reconciliation | yes | I | A | A | A | A | `payment-rails-page.test.tsx`, `capability-state-surface.test.tsx` |
| `/ai-efficiency` | invocations, cost, findings | yes | I | A | A | A | A | `ai-efficiency-page.test.tsx` |
| `/stablecoins` | assets and observed health | no | I | A | A | — | I | parameterized route-state family |
| `/stablecoins/:assetId` | asset deployment and observations | no | I | A | A | — | I | parameterized route-state family |
| `/derivatives` | accounts, positions, reconciliation | no | I | A | A | — | I | parameterized route-state family |
| `/derivatives/accounts/:accountId` | account orders, fills, positions | no | I | A | A | — | I | parameterized route-state family |
| `/agent-access` | agent access grants and audit | yes | A | A | A | A | I | `agent-access-page.test.tsx` |
| `/interoperability` | messages, paths, providers | no | I | A | A | — | I | parameterized route-state family |
| `/interoperability/messages/:messageId` | lifecycle and delivery attempts | no | I | A | A | — | I | parameterized route-state family |
| `/notifications` | notification inbox and unread count | yes | I | A | A | — | I | parameterized route-state family |

## Kyber

| Route | Primary API dependencies | Critical | L | E | R | P | G | Current test evidence |
|---|---|---:|:---:|:---:|:---:|:---:|:---:|---|
| `/mission` | mission rollups, dependencies, alerts | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/live` | live operational events | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/noesis` | operator Noesis | no | I | — | — | — | I | gap |
| `/noesis/graph` | graph explorer | no | I | — | — | — | I | gap |
| `/noesis/fleet` | fleet graph health | no | I | A | — | — | I | `kyber-noncritical-empty-routes.test.tsx` |
| `/entities` | entity fleet | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/entities/:type/:id` | entity detail | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/profile360/:type/:id` | Profile360 and evidence | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/command` | workers, runs, alerts, kill switch | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/diagnostics` | queues and dependencies | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/review` | review batches | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/review/:batchId` | review batch detail | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/lab` | observed experiments | no | I | — | — | — | I | gap |
| `/tenants` | tenant fleet | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/tenants/:tenantId` | tenant detail, keys, billing, usage | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/imports` | import operations | yes | I | A | A | A | I | `imports-ops-page.test.tsx` |
| `/imports/:importId` | import operation detail | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/implementation` | implementation readiness | no | I | A | — | — | I | `kyber-operations-empty-routes.test.tsx` |
| `/implementation/:tenantId` | tenant implementation | no | I | A | — | — | I | `kyber-operations-empty-routes.test.tsx` |
| `/cis` | CIS health, mutation, drift | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/cis/forensics/:nodeId` | CIS node forensics | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/investigations` | investigations | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/investigations/:caseId` | investigation detail | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/packages` | solution packages | no | I | A | A | — | I | `kyber-catalog-route-states.test.tsx` |
| `/packages/:packageId` | solution package detail | no | I | A | A | — | I | `kyber-catalog-route-states.test.tsx` |
| `/deployment-readiness` | deployment readiness | no | I | A | A | — | I | `kyber-catalog-route-states.test.tsx` |
| `/provider-connections` | UPR provider manifest, health, overview, certify | no | A | A | A | A | A | `provider-connections-route-states.test.tsx` |
| `/kyber-graph` | operator topology | yes | A | A | A | A | I | `kyber-graph-page.test.tsx` |
| `/tenant-mirror` | tenant mirror | yes | I | A | A | A | A | `tenant-mirror-page.test.tsx` |
| `/kyber-exceptions` | exception queue | yes | A | A | A | A | A | `kyber-exceptions-page.test.tsx` |
| `/kyber-commands` | governed commands | yes | A | A | A | A | A | `kyber-commands-page.test.tsx` |
| `/reliability` | services, queues, incidents, SLOs | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/journey-health` | journey pipeline health | no | I | A | — | — | I | `kyber-operations-empty-routes.test.tsx` |
| `/reliability/incidents/:incidentId` | incident detail | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/intelligence-quality` | drift and contamination | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/connectors` | connector fleet | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/dune-feeder` | feeder health and jobs | no | I | A | — | — | I | `kyber-noncritical-empty-routes.test.tsx` |
| `/revops` | billing and usage fleet | no | I | A | A | — | I | `kyber-catalog-route-states.test.tsx` |
| `/pricing-architecture` | pricing registry | no | I | A | A | — | I | `kyber-catalog-route-states.test.tsx` |
| `/gtm-materials` | GTM registry | no | I | A | A | — | I | `kyber-catalog-route-states.test.tsx` |
| `/buyer-personas` | persona registry | no | I | A | A | — | I | `kyber-catalog-route-states.test.tsx` |
| `/roi-calculators` | ROI registry | no | I | A | A | — | I | `kyber-catalog-route-states.test.tsx` |
| `/sales-readiness` | sales readiness | no | I | A | A | — | I | `kyber-catalog-route-states.test.tsx` |
| `/security` | security overview | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/security/workforce` | workforce users | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/security/invitations` | invitations | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/security/roles` | roles | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/security/devices` | devices | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/security/sessions` | sessions | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/security/access` | access review | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/security/audit` | security audit | yes | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/rewards` | reward health | no | A | A | A | A | I | `rewards-route-states.test.tsx` |
| `/rewards/:tenantId` | reward tenant detail | no | A | A | A | A | I | `rewards-route-states.test.tsx` |
| `/intelligence/suggestions` | suggestion fleet | no | I | A | — | — | I | `kyber-noncritical-empty-routes.test.tsx` |
| `/intelligence/suggestions/review` | suggestion review | no | I | A | — | — | I | `kyber-noncritical-empty-routes.test.tsx` |
| `/intelligence/semantic-review` | semantic review | yes | A | A | A | A | A | `semantic-review-queue-page.test.tsx` |
| `/ml` | model registry and releases | no | I | — | — | — | I | gap |
| `/fraud-networks` | fraud network fleet | no | I | — | — | — | I | gap |
| `/fraud-networks/flow-trace` | flow trace create | no | I | — | — | — | I | gap |
| `/fraud-networks/flow-trace/:traceId` | flow trace detail | no | I | — | — | — | I | gap |
| `/fraud-networks/:networkId` | fraud network detail | no | I | — | — | — | I | gap |
| `/fraud-networks/risk-360` | Risk 360 subject projection (/v1/risk360) | no | I | A | — | — | I | `kyber-fraud-projection-empty-routes.test.tsx` |
| `/fraud-networks/fraud-360` | Fraud 360 subject projection (/v1/fraud360) | no | I | A | — | — | I | `kyber-fraud-projection-empty-routes.test.tsx` |
| `/measurement` | measurement overview | no | I | A | — | — | I | `kyber-measurement-empty-routes.test.tsx` |
| `/measurement/attribution` | attribution models and runs | no | I | A | — | — | I | `kyber-measurement-empty-routes.test.tsx` |
| `/measurement/journeys` | journey explorer | no | I | A | — | — | I | `kyber-measurement-empty-routes.test.tsx` |
| `/measurement/conversions` | conversion explorer | no | I | A | — | — | I | `kyber-measurement-empty-routes.test.tsx` |
| `/model-runtime/registry` | model-runtime provider registry | no | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/model-runtime/health` | model-runtime provider health | no | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/model-runtime/entitlements` | model-runtime tenant entitlements | no | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/model-runtime/usage` | model-runtime usage meters | no | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/model-runtime/traces` | model-runtime provider traces | no | I | A | A | — | I | `kyber-route-state-family.test.tsx` |
| `/measurement/campaigns` | campaign fleet | no | I | A | — | — | I | `kyber-measurement-empty-routes.test.tsx` |
| `/measurement/campaigns/:campaignId` | campaign detail | no | I | — | — | — | I | gap |
| `/measurement/ops` | measurement operations | no | I | — | — | — | I | gap |
| `/measurement/traffic-intelligence` | traffic intelligence | no | I | A | A | A | I | `traffic-intelligence-ops-page.test.tsx` |
| `/stablecoins/ops` | stablecoin registry and finality | no | I | A | — | — | I | `kyber-operations-empty-routes.test.tsx` |
| `/derivatives/ops` | derivatives adapter fleet | no | I | A | — | — | I | `kyber-operations-empty-routes.test.tsx` |
| `/interoperability/ops` | interoperability providers | no | I | A | — | — | I | `kyber-operations-empty-routes.test.tsx` |
| `/delivery` | delivery operations | no | I | A | — | — | I | `kyber-noncritical-empty-routes.test.tsx` |
| `/agent-telemetry` | agent fleet and telemetry | yes | A | A | A | A | A | `agent-telemetry-page.test.tsx` |
| `/agent-access` | agent access control | yes | A | A | A | A | I | `agent-access-page.test.tsx` |
| `/payment-rails` | payment provider and tenant fleet | yes | A | A | A | A | A | `payment-rails-page.test.tsx` |
| `/ai-efficiency` | AI costs and findings | yes | A | A | A | A | A | `ai-efficiency-page.test.tsx` |
| `/targeting` | targeting and leakage | yes | A | A | A | A | A | `targeting-page.test.tsx` |

| `/intelligence-os` | graph workspace, evidence, investigation memory | no | I | A | n/a | A | I | `kyber-intelligence-os-page.test.tsx` |

## Coverage totals

The denominator is the 137 data-bearing route patterns above: 51 Aether and
86 Kyber routes.

| Metric | Current automated coverage | Requirement |
|---|---:|---:|
| Explicit loading-state assertions | 18 / 137 (13.1%) | tracked for every route |
| Empty-state assertions | 125 / 137 (91.2%) | at least 90% overall |
| Error/unavailable assertions | 105 / 137 (76.6%) | 100% of critical routes |
| Populated-state assertions | 33 / 137 (24.1%) | tracked for every route |
| Critical routes with both empty and error assertions | 62 / 62 (100%) | 62 / 62 (100%) |

These totals count only named automated assertions. Implemented behavior,
generic hook state, or a successful build does not count as coverage.
