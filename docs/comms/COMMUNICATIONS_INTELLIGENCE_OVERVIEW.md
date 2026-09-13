---
title: Communications Intelligence Overview
slug: comms/communications-intelligence-overview
section: architecture
visibility: I
audience: [dev-senior, architect, buyer]
status: experimental
since_version: 0.1.0
source_files: [Backend Architecture/aether-backend/services/comms/contracts.py, Backend Architecture/aether-backend/services/comms/projector.py, Backend Architecture/aether-backend/services/comms/state.py, Backend Architecture/aether-backend/services/silver/dispatcher.py]
source_hashes:
  Backend Architecture/aether-backend/services/comms/contracts.py: sha256:9629e0f07c08f85d43c8b7bd24faf4c2c835a1974ca60d98efad27aa6ff5d961
  Backend Architecture/aether-backend/services/comms/projector.py: sha256:4744e01f562aa331be96730330668f25e0daa14a264f752c90b579f6a567278a
  Backend Architecture/aether-backend/services/comms/state.py: sha256:8a2cb4265352d598cc6a50a1e789f89f1ee88249d003b59902f6d5f4a7c481fc
  Backend Architecture/aether-backend/services/silver/dispatcher.py: sha256:ea6279d0a1242887281ced91e1cb05bc8d94eb4c978f10a6e8615fb4d565f98f
---

# Communications Intelligence Overview

Aether understands email and other communication channels as part of its
holistic intelligence graph. It **observes, normalizes, resolves, connects,
measures, attributes, explains, and surfaces** communications executed
through external providers — it never composes, schedules, or sends them
(ADR-C1, `docs/comms/ADR_COMMUNICATIONS_INTELLIGENCE.md`).

## Pipeline

```
External provider (Klaviyo, generic signed webhook, inbound-parse replies)
  → connector normalization        services/integrations/connectors/klaviyo.py
  → canonical communication event  services/comms/contracts.py (registry family: comms)
  → durable Bronze write + bus     services/comms/ingest.py → SDK_EVENTS_VALIDATED
  → multi-projector Silver fan-out services/silver/dispatcher.py (ADR-C3)
      1. CommsProjector            → silver_comms_facts (authoritative)
      2. IdentityEvidenceProjector → identity evidence
      3. TouchpointProjector       → silver_campaign_touchpoint_facts
  → campaign resolution            services/campaign/resolver.py (existing registry)
  → canonical activity (exactly 1) services/measurement/silver_adapters.py::adapt_comms
  → unified journey                services/measurement/engine/journey_compiler.py
  → attribution eligibility        services/comms/attribution_policy.py (ADR-C8)
  → aggregated graph relationship  services/comms/graph_projection.py (ADR-C6)
  → communication state            services/comms/state.py (rebuildable reducer)
  → Profile360 / Campaign 360 / Noesis / Kyber health
```

## Channels and events

Email-first, channel-agnostic by design. The canonical taxonomy lives in
`packages/shared/contracts/event-registry.json` (family `comms`):

- Email lifecycle: `email_queued/processed/sent/delivered/deferred/bounced/
  dropped/opened/clicked/replied/spam_complaint/suppressed`,
  `unsubscribe_observed`
- Channel-neutral: `message_sent/received/replied_observed`,
  `notification_delivered/opened/clicked`

The same architecture extends to SMS, push, support messaging, and
human/agent communications by adding events to the registry and mapping
tables in `services/comms/contracts.py` — no new pipeline is required.

## Measurement quality

- **Reported vs human-qualified engagement** — every open/click is
  classified deterministically (`services/comms/classification.py`):
  scanner user-agents, privacy proxies, datacenter IPs, scanner-window
  clicks, and repeated-link patterns mark `suspected_machine_activity`.
  Machine engagement never earns journey steps, touchpoints, or attribution
  credit; it remains visible as a quality metric.
- **Replies** — inbound replies correlate via In-Reply-To / References /
  provider thread / reply-token (`services/comms/replies.py`); DSN,
  out-of-office, and loop responses are excluded from engagement.
- **Attribution** — delivery is context-only; reported opens are excluded by
  default; human-qualified clicks are eligible; replies are tenant-configurable;
  transactional mail never earns acquisition credit.

## Privacy

Raw addresses are normalized, HMAC-hashed tenant-scoped, and redacted for
display (`services/comms/mailbox.py`). Bodies and attachments are never
stored by default; subjects are used transiently for automated-response
detection only. Shared/role mailboxes (`sales@`, `support@`, …) resolve to
organizations, never to individual humans.

## Surfaces

- **Profile360**: `GET /v1/profile/{id}/communications` (filterable, cursor
  paginated) and `GET /v1/profile/{id}/communication-state`; Communications
  tab in the tenant frontend.
- **Campaign 360**: `GET /v1/campaigns/{id}/messages`, `/messages/{ext_id}`,
  `/links`, `/comms-funnel` (provider-reported vs human-qualified modes),
  `/comms-population` (recipient stages + flag filters); Messages tab with
  message-detail drawer and Recipients section in the tenant frontend.
- **Initiatives**: `POST/GET /v1/comms/initiatives`, member management,
  `GET /v1/comms/initiatives/{id}/rollup` — cross-channel macro rollup over
  canonical campaigns (ADR-C9; no second registry).
- **Kyber**: `GET /v1/comms/admin/health` fleet view; Communications
  pipeline health card on the Measurement Operations page.
- **Noesis**: `communications_insight` intent — evidence-backed, read-only.

## Rollout

Feature flags (`config/settings.py::CommsConfig`):
`AETHER_COMMS_{INGESTION,CAMPAIGN_PROJECTION,JOURNEYS,GRAPH,PROFILE360,CAMPAIGN360,NOESIS}_ENABLED`.
See `docs/comms/COMMS_RELEASE_READINESS.md` for the rollout and rollback plan,
and `tests/integration/test_comms_golden_scenario.py` for the permanent
golden release fixture.
