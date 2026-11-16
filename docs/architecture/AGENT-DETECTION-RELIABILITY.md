---
title: Agent Detection Reliability — Current-State Assessment
slug: architecture/agent-detection-reliability
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: 0.1.0
source_files: [services/api/journeys/traffic/classifier.py, services/api/ingestion/silver/projectors/touchpoint_projector.py, services/api/journeys/measurement/engine/attribution_engine.py, services/api/journeys/measurement/silver_adapters.py, packages/sdk/web/src/utils/index.ts, packages/sdk/server/src/agentic.ts, services/api/actions/agent/attestation.py, services/api/actions/agent_lineage/engine.py, services/api/actions/agent_lineage/evidence.py, services/api/config/settings.py]
related: [operations/agent-layer-production, plans/public-agent-registry]
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
source_hashes:
  "packages/sdk/server/src/agentic.ts": "sha256:da675cdd08068013c1700c8e65943b55a31950c3399b2efb8b67cb08af4107db"
  "packages/sdk/web/src/utils/index.ts": "sha256:d3a7e25ac23db1dbc7eab37c74e8970bb69b8a9524c6ef5c6fabc438447dfc4d"
  "services/api/actions/agent/attestation.py": "sha256:d0930009a39420b36c083d51ba05cbd2261d6a7aa66589c9509fb62707199655"
  "services/api/actions/agent_lineage/engine.py": "sha256:7892db12bd711f33c57ab75829afd018a9866c610856249a0d1cf8b135fac1c5"
  "services/api/actions/agent_lineage/evidence.py": "sha256:80870d50700b4c9f1e6e04d20da5a49476edf52475a8dee9c1779937ba5738cc"
  "services/api/config/settings.py": "sha256:9a66f5308e8c08ac85cc1edc084e5062008564eb5ed90cde2bb49f49cbdcf8ee"
  "services/api/ingestion/silver/projectors/touchpoint_projector.py": "sha256:0234e2146b1ec5626754f6bcd96a0013bb71d2c4fe766a20a4e9620d6fbbc60e"
  "services/api/journeys/measurement/engine/attribution_engine.py": "sha256:f933e4895eeb931f50757a1789081f6a4bc92461bd1de3ece2424b1d918cc0d9"
  "services/api/journeys/measurement/silver_adapters.py": "sha256:d69f12e7e527d0f3244b355bae6025dbd9dbae4f38ec35acc66ff505459fab70"
  "services/api/journeys/traffic/classifier.py": "sha256:3635e38f7e4417295514d3188d788c6b6c2ec7a32920e233872ca94bbcdde88f"
---

# Agent Detection Reliability — Current-State Assessment

**Question:** how reliably does Aether track AI agents today, through the
surfaces customers actually install (SDKs, server integrations, webhooks)?

**Answer:** reliably only for agents that are explicitly instrumented, and
strongly only when they sign their events. Agents that announce themselves with
a well-known user-agent are labelled, but the label is unverified and claimed
more strongly than the evidence allows. Agents that do not announce themselves
are not detected at all, and the pipeline **counts them as humans**.

This page describes what the code does today, with file references, and the
ordered remediation. It is an assessment, not a readiness claim; see
`scripts/production_status.py` for the readiness scorecard.

## 1. Reliability by observation path

| Path | What the code does today | Strength reached | Reliability |
|---|---|---|---|
| Server SDK agent events, deployment has a registered Ed25519 key | Signature over event identity + property/lineage hash is verified (`services/api/actions/agent/attestation.py`); the event is recorded `attested` | Cryptographically attested | **High** — but only when the deployment registry is on (`AETHER_AGENT_DEPLOYMENT_REGISTRY_ENABLED`, default `false` in `services/api/config/settings.py`) |
| Server SDK agent events, unsigned | `actor_type`, `delegated_by`, `verification_status` are fields the sender fills in (`packages/sdk/server/src/agentic.ts`, `AuthorizationContext` / `VerificationContext`) | Source-reported | **Medium** — correct for honest integrations, unverifiable otherwise |
| Delegation / authority records | Lineage resolver separates verified from tenant-declared records, refuses grants over an agent from anyone but its registered owner, and never treats an agent id named as principal as attribution (`services/api/actions/agent_lineage/engine.py`, `evidence.py`) | Verified authority / declared | **High** for the relationship model itself; it depends on authority records existing |
| Declared AI user-agents (`GPTBot`, `ChatGPT-User`, `ClaudeBot`, `Claude-User`, `PerplexityBot`, …) | Substring match on the user-agent string (`classifier.py`, `MACHINE_USER_AGENTS` / `AGENT_USER_AGENTS`) | Labelled `server_observed`, confidence 0.98 / 0.92 | **Low–medium** — see §2.2 |
| Web SDK, agent driving a real browser | No automation evidence is captured: no `navigator.webdriver`, no interaction-presence or cadence signals. The only actor-relevant field is `navigator.userAgent` (`packages/sdk/web/src/utils/index.ts`) | None | **None** — such agents are indistinguishable from humans |
| Web SDK, agent fetching pages without running JS | Most declared AI fetchers do not execute JavaScript, so the browser SDK never fires | None | **None** on SDK-only sites |
| Mobile SDKs | No actor or automation evidence captured | None | **None** |
| Webhooks / connectors | Actor is whatever the provider exposes; nothing is inferred | Provider-asserted, when present | **Varies by provider**; not audited per connector here |
| MCP OAuth client identity, A2A Agent Cards, Web Bot Auth signatures, provider IP-range / reverse-DNS checks | Not implemented | — | **None** |

## 2. Findings

### 2.1 Missing evidence becomes "human" (highest impact)

When no actor evidence is present, three layers default the actor to `human`:

- `services/api/journeys/traffic/classifier.py` — the non-machine branches
  return `actor_type=explicit_actor_type or "human"` (ten call sites, including
  the direct / unknown fallback).
- `services/api/journeys/measurement/engine/attribution_engine.py` —
  `_touchpoint_to_resolver_dict` sets `human` whenever a `profile_id` or
  `anonymous_id` exists, and web SDK events carry an `anonymous_id`.
- `services/api/journeys/measurement/silver_adapters.py` —
  `row.get("actor_type") or "human"`.

Consequence: every undetected agent is recorded as a human. Human share is
overstated, agent share understated, and **no metric can show the size of the
gap**, because "we don't know" is never recorded as such.

### 2.2 User-agent matches are claimed as stronger than they are

The UA branch reports `proof_level="server_observed"` with confidence 0.98
(crawler) or 0.92 (agent). Two problems:

1. On the SDK path the user-agent comes from the **client payload**
   (`ctx.userAgent`, set from `navigator.userAgent`, read in
   `touchpoint_projector.py`), not from a request the server saw. Only the
   verified-link redirect route reads the real request header.
2. Even a real header is trivially spoofable. Nothing checks it against the
   provider's published IP ranges, reverse DNS, or a Web Bot Auth signature.

A UA match is evidence that a request **declares** itself an agent, not that
it is one. The correct ceiling without verification is `declared`.

### 2.3 Strong verification exists but is off by default

The Ed25519 attestation path and the lineage resolver are the most rigorous
parts of the system, and both are correctly designed (claims are kept separate
from canonical resolution; unverified records cannot prove a principal link).
They sit behind `AETHER_AGENT_DEPLOYMENT_REGISTRY_ENABLED=false`, so in a
default deployment the strong path is not live.

### 2.4 Nothing measures detection reliability

There is no metric for the share of agent-classified events by evidence class,
or for the share of events whose actor is unresolved. Without one, reliability
cannot be reported to customers or tracked over time.

## 3. What we can honestly claim today

- **Can claim:** Aether attributes agent activity reported through the server
  SDK, with cryptographic proof for deployments that sign their events, and
  models delegation and authority with explicit verified / declared states.
- **Can claim, with qualification:** Aether labels traffic from AI providers
  that declare themselves by user-agent. The label is not verified.
- **Cannot claim:** that Aether detects AI agents in general, that it
  distinguishes agents from humans on web or mobile SDK traffic, or that
  human-share metrics exclude agents.

## 4. Remediation, in order

| # | Change | Effect | Touches |
|---|---|---|---|
| 1 | Record `unknown` instead of defaulting to `human` when there is no actor evidence | Stops undetected agents being counted as humans; makes the gap measurable. Changes downstream attribution, so it needs a restatement plan and a release note | `classifier.py`, `attribution_engine.py`, `silver_adapters.py`, attribution consumers |
| 2 | Cap UA-only matches at `declared`; promote to `platform_verified` only when the source IP matches the provider's published ranges or reverse DNS | UA labels stop overclaiming | `classifier.py`, traffic-source registry proof ceilings |
| 3 | Verify Web Bot Auth (HTTP Message Signatures) on server ingress and verified-link redirects | Cryptographic identity for agents that sign web requests | ingestion gateway, `traffic/routes.py` |
| 4 | Web SDK automation evidence: `navigator.webdriver`, presence/absence of pointer and keyboard input, interaction cadence. Output is `automation` / `BEHAVIORALLY_INFERRED` only — never `agent`, never verified | First signal on agents driving real browsers, without biometrics | `packages/sdk/web`, consent registry (new signal purpose), touchpoint projector |
| 5 | Enable the deployment registry and event signing by default for agent integrations; show unsigned agent events as `source_reported` | The strong path becomes the default path | `settings.py`, server SDK docs, Agent 360 UI |
| 6 | Capture MCP OAuth `client_id` / authorized party; ingest A2A Agent Cards (signed JWS) as agent identity evidence | Protocol-level identity for MCP and A2A agents | `actions/agent_correlation`, observation envelope `protocol` block |
| 7 | Detection-reliability metric: share of events by actor kind × evidence class, including `unknown` | Reliability becomes reportable and trackable | metrics registry, Kyber health |

Items 1, 2 and 7 are small and should land first: they make the system honest
about what it does not know before it learns more.

## 5. Out of scope here

Detection with **no** SDK, server integration, webhook or connector installed
is a separate product question, covered in
[Public Agent Registry](plans/PUBLIC-AGENT-REGISTRY.md). Nothing in that design
changes the findings above.
