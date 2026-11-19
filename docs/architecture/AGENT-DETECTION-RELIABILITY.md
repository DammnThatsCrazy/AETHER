---
title: Agent Detection Reliability — Assessment and Remediation
slug: architecture/agent-detection-reliability
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: 0.1.0
source_files: [services/api/journeys/traffic/classifier.py, services/api/journeys/traffic/agent_verification.py, services/api/journeys/traffic/metrics.py, services/api/ingestion/ingestion/batch.py, services/api/ingestion/silver/dispatcher.py, services/api/ingestion/silver/projectors/touchpoint_projector.py, services/api/journeys/measurement/engine/attribution_engine.py, services/api/journeys/measurement/engine/journey_compiler.py, services/api/journeys/measurement/silver_adapters.py, packages/sdk/web/src/utils/index.ts, packages/sdk/web/src/types.ts, packages/sdk/server/src/agentic.ts, services/api/actions/agent/attestation.py, services/api/actions/agent_lineage/engine.py, services/api/actions/agent_lineage/evidence.py, services/api/config/settings.py]
related: [operations/agent-layer-production, plans/public-agent-registry]
canonical_owner: platform@aether
estimated_read_minutes: 10
toc_depth: 3
source_hashes:
  "packages/sdk/server/src/agentic.ts": "sha256:da675cdd08068013c1700c8e65943b55a31950c3399b2efb8b67cb08af4107db"
  "packages/sdk/web/src/types.ts": "sha256:0b12cb075729098df014e453361ce3d42c47b016db643350bc8a44dfd03344a9"
  "packages/sdk/web/src/utils/index.ts": "sha256:69d575c70eba14c95cd7f0b82659bf7db7c8c3151dbb63d05fefcb4b137412ce"
  "services/api/actions/agent/attestation.py": "sha256:d0930009a39420b36c083d51ba05cbd2261d6a7aa66589c9509fb62707199655"
  "services/api/actions/agent_lineage/engine.py": "sha256:7892db12bd711f33c57ab75829afd018a9866c610856249a0d1cf8b135fac1c5"
  "services/api/actions/agent_lineage/evidence.py": "sha256:80870d50700b4c9f1e6e04d20da5a49476edf52475a8dee9c1779937ba5738cc"
  "services/api/config/settings.py": "sha256:9a66f5308e8c08ac85cc1edc084e5062008564eb5ed90cde2bb49f49cbdcf8ee"
  "services/api/ingestion/ingestion/batch.py": "sha256:c5d2ead7250540a36dd23b7ab42297e4e1ed22d1c0b8972c5a670f5e4e6e1229"
  "services/api/ingestion/silver/dispatcher.py": "sha256:f1ac1e82dd95a777fdc182b5f5c1451548c9cf3208b5bd0651d99f299910a4fb"
  "services/api/ingestion/silver/projectors/touchpoint_projector.py": "sha256:9edfd1c1151cacb056c493c8a105cd09dbde12e7cb3bbd44e2b22b14d871704e"
  "services/api/journeys/measurement/engine/attribution_engine.py": "sha256:a4d7048ab540db38e948daf17c411ec610887107934d42253d0be9a2c7f252c9"
  "services/api/journeys/measurement/engine/journey_compiler.py": "sha256:5cb88fcdb807f9dc52e1cf6e3966d81f6b9f4509a5cdc1517300bed6ce1179df"
  "services/api/journeys/measurement/silver_adapters.py": "sha256:084dfd921dce491ec3eceb43d494a3afbb4e7bfdf580486b21b6c512e2266165"
  "services/api/journeys/traffic/agent_verification.py": "sha256:06839e165b37e38db25690424e427419978585ac4105ff836b6adf2bc0171341"
  "services/api/journeys/traffic/classifier.py": "sha256:6e2868956bae03ba746e0ebc2f2b626d4729a82944638423be0b46c9214732d6"
  "services/api/journeys/traffic/metrics.py": "sha256:6f6a97826153619931bf04d7c3c865c2896d976b4cb834c14444989ed4ac1cc4"
---

# Agent Detection Reliability — Assessment and Remediation

**Question:** how reliably does Aether track AI agents through the surfaces
customers install (SDKs, server integrations, webhooks)? A human / agent graph
is only as trustworthy as the weakest path feeding it.

**Target:** every path at **medium** reliability or better, **high** where the
evidence allows. "Reliable" here means two things: what we label, we label
correctly and at the right strength; and what we cannot see, we record as
`unknown` instead of guessing.

**Status:** Phase 1 (§3) is implemented. It fixes the three highest-impact
problems and adds browser automation evidence. Five paths are at medium or
better; three are not yet, and §5 lists what closes each gap. This page is an
engineering assessment, not a readiness claim; see `scripts/production_status.py`.

## 1. Reliability by path

| Path | Before Phase 1 | After Phase 1 | Why |
|---|---|---|---|
| Server SDK events, signed (Ed25519) | High, registry off by default | **High**, registry still off by default | `attestation.py` verifies signatures; enabling `AETHER_AGENT_DEPLOYMENT_REGISTRY_ENABLED` is a deployment decision (§5) |
| Server SDK events, unsigned | Medium | **Medium** | Fields are source-reported; recorded as such |
| Delegation / authority records | High | **High** | Lineage resolver separates verified from declared, owner-only grants |
| Declared AI user-agents (GPTBot, ChatGPT-User, PerplexityBot, …) | Low–medium, overclaimed | **High** where the provider publishes IP ranges; **medium** otherwise | Server checks the real header + client IP against published ranges; unverifiable claims are labelled `declared` |
| Undetected actors (all web / mobile traffic) | Counted as **human** | **Correctly `unknown`**, and measured | No more human default anywhere in the touchpoint, attribution, adapter or journey path |
| Browser automation (WebDriver-driven browsers) | None | **Medium** (inferred) | Web SDK reports `navigator.webdriver`; classified `machine`, never `agent` or `human` |
| Agent in a real browser without WebDriver (CDP, extensions, computer-use) | None | **None** — recorded `unknown` | No honest client signal exists; needs Web Bot Auth or an agent credential (§5) |
| Agent that does not run JavaScript, on an SDK-only site | None | **None** — invisible | Needs a server-side integration (§5) |
| Mobile SDKs | None | **None** — recorded `unknown` | No actor evidence captured yet (§5) |
| MCP client identity, A2A Agent Cards, Web Bot Auth | None | **None** | Phase 2 (§5) |

"Detection reliability" is now itself measured: `actor_detection_total
{actor_type, proof_level, verification_level}` (§3.3). The share labelled
`unknown` is the size of the remaining gap.

## 2. Baseline findings (before Phase 1)

1. **Missing evidence became "human."** `classifier.py` returned
   `explicit_actor_type or "human"` in ten branches; `attribution_engine.py`
   set `human` for any touchpoint with an `anonymous_id` (every web SDK event);
   `silver_adapters.py` hard-coded `human` for touchpoints, web3 transactions,
   identity evidence, outcomes, revenue, exposure, account activity and
   conversions; `journey_compiler.py` defaulted both sides of a transition to
   `human`. Every undetected agent was counted as a person.
2. **User-agent matches overclaimed.** A substring match on a client-supplied
   user-agent was labelled `server_observed` with confidence 0.98 / 0.92, with
   no check against the provider's published IP ranges.
3. **The strong path was off by default and nothing measured reliability.**
4. **No automation evidence** was captured by any SDK.

## 3. Phase 1 — implemented

### 3.1 `unknown` instead of `human`

Actor type is set only from evidence: a declared actor, an `agentId`, a
verified or declared agent user-agent, or the automation flag. Otherwise it is
`unknown`.

- `classifier.py`: all no-evidence branches return `unknown`.
- `attribution_engine.py`: an identity id no longer implies a human.
- `silver_adapters.py`: every adapter uses the row's own `actor_type`, else
  `unknown`.
- `journey_compiler.py`: `unknown → agent` is not a `human_to_agent` handoff.

Effect on attribution: `ActorWeightedModel` weights `unknown` touchpoints at
1.0 (neutral) instead of the human weight (0.7). Journeys and attribution
results computed before this change will differ when recomputed; restatement
follows the existing reclassification path.

### 3.2 Graded verification of declared agents

`journeys/traffic/agent_verification.py` runs during `/v1/batch` ingestion
(`batch._build_agent_verification`). It reads the request's own `User-Agent`
header and the trusted client IP (`context_enricher.resolve_client_ip`, which
ignores forwarded headers from untrusted peers). It checks the IP against the
provider's published ranges in `agent_provider_ranges.json`, and writes only
`{ua_signature, verification}` to `server_context.agent_verification`. The raw
IP is never stored.

| Evidence | `proof_level` | `verification_level` | Confidence |
|---|---|---|---|
| Payload user-agent only | `declared` | `user_agent_claim` | 0.5 |
| Real request header | `declared` | `user_agent_header` | 0.7 |
| Header, IP outside published range | `declared` | `user_agent_ip_mismatch` | 0.3 |
| Header, IP inside published range | `platform_verified` | `provider_ip_range` | 0.95 (agent) / 0.98 (crawler) |

The server-observed header wins over a conflicting payload claim. Ranges are
refreshed with `scripts/refresh_agent_provider_ranges.py` (OpenAI GPTBot,
ChatGPT-User, OAI-SearchBot; PerplexityBot, Perplexity-User). Providers that
publish no machine-readable range list stay `declared`; endpoints are never
guessed.

### 3.3 Reliability metric

`actor_detection_total{actor_type, proof_level, verification_level}` is
emitted for every classified touchpoint (`dispatcher._emit_classification_metrics`,
`journeys/traffic/metrics.py`). All labels are bounded classifier vocabulary.

### 3.4 Browser automation evidence

The web SDK adds `context.device.automation = {webdriver, trustedInputSeen}`
(`packages/sdk/web/src/utils/index.ts`). Both are presence booleans: no
timings, coordinates, key values or movement patterns are read, so nothing
biometric is collected. The projector maps `webdriver: true` to
`actor_type: machine` with evidence `actor:webdriver_flag`. A declared actor or
`agentId` takes precedence. `webdriver: false` and `trustedInputSeen: true` are
**not** treated as evidence of a human: automation can produce trusted events.

## 4. What we can claim after Phase 1

- **Can claim:** agents reported through the server SDK are attributed, with
  cryptographic proof for signing deployments. Declared OpenAI and Perplexity
  agents and crawlers are verified against the providers' published ranges.
  WebDriver-driven browsers are flagged as automation. Aether never counts an
  actor as human without evidence, and reports how much traffic is unresolved.
- **Cannot claim:** that Aether detects agents that hide, or agents driving a
  real browser without WebDriver, or anything on mobile, or that `unknown`
  traffic is human.

## 5. Phase 2 — closing the remaining gaps

| Gap | Change | Reaches |
|---|---|---|
| Strong path off by default | Enable the deployment registry and event signing by default for agent integrations; show unsigned agent events as `source_reported` in Agent 360 | High for instrumented agents by default |
| Real-browser agents without WebDriver | Verify Web Bot Auth (HTTP Message Signatures) on `/v1/batch` and verified-link redirects | High for agents that sign; others stay `unknown` |
| Non-JS agents on SDK-only sites | Server SDK request-evidence helper (forward the real request's user-agent and signature headers from the customer's server) | Medium–high |
| Mobile | App-attestation and accessibility-automation evidence in the mobile SDKs | Medium (inferred) |
| MCP / A2A agents | Capture MCP OAuth `client_id` / authorized party; ingest signed A2A Agent Cards | High |
| Providers without published ranges | Add providers to `refresh_agent_provider_ranges.py` as they publish ranges; reverse-DNS verification where documented | High per provider |

Detection with no SDK, server integration, webhook or connector installed is a
separate, unscheduled product question:
[Public Agent Registry](plans/PUBLIC-AGENT-REGISTRY.md).
