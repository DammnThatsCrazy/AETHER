---
title: AI and Agent Referral Attribution Source of Truth
status: stable
source_files:
  - Backend Architecture/aether-backend/services/traffic/classifier.py
  - Backend Architecture/aether-backend/services/traffic/referral_links.py
  - Backend Architecture/aether-backend/services/traffic/repair.py
  - Backend Architecture/aether-backend/services/ingestion/acquisition_privacy.py
  - Backend Architecture/aether-backend/services/silver/dispatcher.py
  - Backend Architecture/aether-backend/services/silver/projectors/touchpoint_projector.py
  - Backend Architecture/aether-backend/services/measurement/engine/journey_compiler.py
  - Backend Architecture/aether-backend/services/measurement/engine/attribution_engine.py
  - Backend Architecture/aether-backend/services/measurement/engine/gold_materializer.py
  - Backend Architecture/aether-backend/services/measurement/routes/kyber.py
  - Backend Architecture/aether-backend/services/profile/aggregator.py
last_synced_commit: pending
---

# AI and Agent Referral Attribution

AI-mediated acquisition extends Aether's existing measurement path. It does not
own campaign identity, compile a second journey, allocate credit independently,
or publish a separate measurement result.

```text
SDK acquisition evidence
  -> privacy-safe Bronze/outbox evidence
  -> canonical source classification
  -> existing Silver touchpoint
  -> existing campaign resolver
  -> existing versioned journey compiler
  -> existing attribution engine and credits
  -> existing Gold materialization and restatement
  -> Aether and Kyber
```

## Ownership boundaries

| Question | Authoritative component |
|---|---|
| What raw landing evidence was observed? | Existing SDK and ingestion path |
| What does the touchpoint represent? | Source classifier version `2.0` |
| Which campaign owns the evidence? | Existing campaign resolver and registry |
| How is conversion credit allocated? | Existing attribution engine and models |
| How is corrected history published? | Existing Measurement Integrity Plane |

AI providers and products are source dimensions, never campaign identities.
Campaign IDs continue to be accepted only through the canonical campaign
resolver and tenant-owned aliases.

## Classification contract

The classifier is deterministic and campaign-agnostic. Its precedence is:

1. machine, scanner, crawler, or link-preview user-agent evidence;
2. a server-verified `aether_ref` referral link;
3. paid click identifiers;
4. declared UTM evidence;
5. a normalized referrer domain;
6. direct entry.

The canonical touchpoint retains the backward-compatible `source`, `medium`,
and `channel` fields and adds:

- `source_class` and `referral_mediation_type`;
- normalized `ai_provider` and `ai_product`;
- `actor_type` and `journey_role`;
- `evidence_confidence` and `verification_level`;
- `source_classifier_version` and `source_classification_id`;
- `attribution_eligible` and `verified_referral_link_id`;
- `normalized_referrer_domain` and a one-way `referrer_path_hash`.

Supported mediation values distinguish ordinary, AI-mediated human,
agent-mediated, owned-agent, partner, affiliate, crawler, preview, scanner,
unknown external, and direct traffic. Machine-only crawler, preview, and
scanner observations remain visible for discovery reporting but are excluded
from attribution.

## Privacy and verification

Ingestion strips the raw `aether_ref` value from stored URLs, replaces the token
with a SHA-256 digest before Bronze or outbox persistence, reduces referrers to
their origin, and stores only a one-way path fingerprint when path evidence is
needed. Raw query strings, fragments, and referral tokens are not canonical
touchpoint fields.

Verified referral links are tenant-scoped evidence records. The public token is
returned once on creation; only its digest is stored. Resolution checks tenant,
status, and expiry. Link-use counting is replay-safe by source event ID. A
verified link may supply placement, agent, campaign, provider, product, and
mediation evidence, but campaign ownership is still checked by the campaign
resolver.

The create and revoke endpoints require referral-link write access; listing
requires read or write access. Viewer and browser keys are kept outside this
control plane. Repository reads and foreign keys retain tenant IDs so a link,
classification revision, job, journey, or attribution run cannot cross tenants.

## Durable history and recomputation

Classification evaluations are append-only and deduplicated by touchpoint,
classifier version, and evidence input hash. Replaying the same evaluation is a
no-op; a new evidence hash records a revision even when the canonical output is
unchanged so the evidence lineage remains auditable. The current touchpoint
points to a `source_classification_id`, while
`touchpoint_source_classification_revisions` retains the prior and replacement
payloads, classifier version, reason, job ID, and timestamp. Completed
attribution runs and credits are never rewritten.

Kyber starts an internal durable job for a bounded date range. The repair job:

1. pages historical touchpoints and classifies them with the current version;
2. appends or reuses the version-and-input-hash classification revision;
3. rebuilds affected profile or cluster journeys as new versions;
4. runs the existing attribution engine for affected canonical conversions;
5. activates the new attribution run and credits atomically;
6. rematerializes the full affected conversion-date range with an explicit
   restatement reason.

The attribution run stores its effective model-policy snapshot. A recomputation
reuses that snapshot unless an operator explicitly selects another model
configuration, preserving click/view windows, identity thresholds, fraud
policy, direct-traffic policy, and engaged-view thresholds.

## Product and operator surfaces

Aether's Campaign 360 and Profile 360 journey views expose provider, product,
mediation, actor, journey role, verification, eligibility, and attributed net
revenue on the existing drill-downs. No third frontend is introduced.

Kyber exposes:

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/v1/kyber/measurement/source-classification/health` | Tenant-scoped version, provider, mediation, verification, and exclusion health |
| `POST` | `/v1/kyber/measurement/source-classification/reclassify` | Enqueue dry-run or live historical repair |
| `POST` | `/v1/referral-links` | Create a controlled verified link |
| `GET` | `/v1/referral-links` | List tenant-owned link metadata |
| `POST` | `/v1/referral-links/{id}/revoke` | Idempotently revoke a link |

Kyber repair requests accept a caller-stable `request_id`. Retries with the same
ID replay the existing durable job; an intentional rerun must use a new ID.

## Invariants

- Existing source values and unclassified historical rows remain readable.
- Source classification does not resolve or invent a campaign.
- Only canonical conversions and revenue facts enter attribution.
- Journey version activation and step creation are atomic.
- Attribution credit activation is atomic and tenant-scoped.
- Corrected measurement results supersede prior publications; they do not
  overwrite them.
- Crawler and scanner evidence remains observable but cannot receive credit.
- No AI-only touchpoint table, attribution engine, campaign registry, job queue,
  measurement store, or frontend exists.
