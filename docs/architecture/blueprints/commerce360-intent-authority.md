---
title: Commerce360 Intent Authority
slug: concepts/commerce360-intent-authority
section: concepts
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "0.1.0"
source_files:
  - packages/shared/contracts/intelligence-projection-registry.json
  - services/api/alembic/versions/20261023_commerce_intent_authority.py
  - services/api/tests/unit/test_commerce_intent_authority.py
  - services/api/value/commerce/commerce360_provider.py
  - services/api/value/commerce/commerce_intents.py
source_hashes:
  "packages/shared/contracts/intelligence-projection-registry.json": "sha256:2f400c148c9f190874adc75f8dd78b631cc1fb2f787febfa0fdac7ce0f4fdee4"
  "services/api/alembic/versions/20261023_commerce_intent_authority.py": "sha256:81dbf80e8646034fe5f2b51e616ee71c4c758b6a4380b3ee44ff5ce114156e38"
  "services/api/tests/unit/test_commerce_intent_authority.py": "sha256:2f80185b0b0ae04a08b2342152b81a311b017ce2cf87ded2ca8aa615b08fad87"
  "services/api/value/commerce/commerce360_provider.py": "sha256:635f93631d2946d681c9f3d98c8f6b2bb929fc9a200c42b70afeeacdd49b085c"
  "services/api/value/commerce/commerce_intents.py": "sha256:c452c03579bc73e3df33a817ee97edea530d5954450c8d3a25635904120ba1d0"
canonical_owner: commerce@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Commerce360 intent authority

This document defines the explicit commerce intent source and its Commerce360
read path. The intent authority records declarations made by a tenant actor; it
does not infer intent from product exposure, views, cart changes, checkout
starts, payment attempts, or campaign targeting.

## Ownership and supported subjects

`services/api/value/commerce/commerce_intents.py` owns typed intent records and
the append-only `CommerceIntentRepository`. Each record is tenant scoped and
references one exact canonical product or offer ID already present in the
tenant's product/offer catalog at the record's effective time. An offer
declaration is therefore validated against the tenant's offer record, not
matched by name, URL, provider payload, or a behavioral event.

This first provider path supports `product` and `offer` subjects. It does not
claim coverage for `commerce`, `sku`, or `checkout` subjects; those need their
own canonical authorities and explicit joins.

Intent kinds are `purchase`, `subscription`, `renewal`, `replenishment`, and
`comparison`. Lifecycle state is one of `declared`, `active`, `fulfilled`,
`abandoned`, `withdrawn`, or `expired`. A later source revision updates the
state of the same `intent_id`; revisions remain immutable.

## Write paths and provenance

The authenticated human declaration endpoint is `POST /v1/commerce/intents`.
It requires `commerce:write` and a server-authenticated user principal. The
request supplies an idempotency key, exact product/offer subject, intent kind,
state, and optional effective time. The service assigns the actor, observation
time, source provider (`aether_commerce_intent_api`), source record/revision
identifiers, and an annotation evidence reference. Actor identity is never
accepted from the request body.

Trusted internal writers may call `CommerceIntentRepository.record_intent()`
with the typed actor and source/evidence fields supplied by their canonical
source. They must preserve an intent ID across lifecycle revisions and use a
new source revision and idempotency key for each new immutable fact.
The repository validates tenant and canonical subject ownership but does not
evaluate agent delegation or execution authority; agent writers must pass
their own authority checks before writing. No agent-specific declaration route
is provided by this slice.

Idempotency is unique within a tenant. Replaying the same declaration returns
the stored record, including its original observed time. Reusing a key or
source revision for changed declaration content returns a conflict. A source
revision must carry evidence whose source and ID match the record's exact
source provider and source record ID.

## Read and completeness semantics

`RepositoryCommerceIntentEvidenceSource` first verifies the requested product
or offer against the same tenant's canonical catalog at the requested
`asOf`. It then reads the latest effective revision per intent where both
`effective_at` and `observed_at` are no later than that anchor. Reads are
bounded to 500 current intent IDs per subject.

The `intent` section reports:

| State | Meaning |
| --- | --- |
| `available` | One or more exact intent declarations were read completely. |
| `empty` | The canonical subject exists and this authority has no explicit intent records at the anchor. This does not assert an absence of unobserved intent outside AETHER. |
| `missing` | The requested product/offer is absent from this tenant's canonical catalog at the anchor. |
| `unknown` | Scope, source, timestamp, or provenance could not be verified. |
| `degraded` | The list was truncated, malformed, or marked partially complete. |

The provider carries actor, effective and observed times, source revision, and
evidence references into the section. It emits observed claims only from
validated records. The evidence trace includes intent evidence. It preserves
source timestamps and reports freshness as `unknown` until a source-specific
freshness threshold is configured. Existing frame policy remains responsible
for any customer-facing redaction.

## Projection binding

The product-surface slot `commerce360.intent` is bound only for the implemented
canonical subject kinds:

```json
{
  "id": "intent",
  "requirement": "required",
  "description": "Explicit tenant-owned intent records joined to an exact product or offer subject, with actor, source revision, timestamps, and evidence.",
  "canonicalAuthorityRefs": [
    "commerce_intent_authority",
    "commerce_product_offer_graph",
    "source_provenance"
  ],
  "projectionBindings": [
    {
      "projectionId": "commerce360",
      "role": "primary",
      "subjectKinds": ["offer", "product"],
      "sectionIds": ["intent"]
    }
  ],
  "partialImplementationReason": "explicit_intent_subject_join_is_implemented_for_product_and_offer_only; commerce_sku_and_checkout_authorities_are_not_connected; freshness_threshold_is_unconfigured"
}
```

This binding does not declare the overall Commerce360 surface complete. The
other required slots and unsupported intent subjects remain independently
tracked.
