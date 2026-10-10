---
title: Events and Consent
slug: developers/events-and-consent
section: developer
visibility: P
audience: [dev-junior, dev-senior, architect, security, compliance]
status: stable
since_version: "8.12.0"
estimated_read_minutes: 6
toc_depth: 3
canonical_owner: platform@aether
---
# Events and Consent
Every connection should carry enough context for Aether to understand where an
observation came from and whether the deployment allows it to support a
relationship or perspective.
## Minimum event context
Use the canonical event contracts and preserve, where available:
- tenant and source identity;
- subject, anonymous, or actor identifiers;
- consent and processing-basis context;
- event time and ingestion time;
- provenance, freshness, and source quality;
- journey, campaign, communication, or episode context; and
- schema and contract versions.
## Consent is a processing boundary
Consent controls whether data may be collected, linked, projected into the
graph, retained, used for model training, or used to activate a downstream
action. A transport path such as an SDK or webhook does not override those
boundaries.
When consent or required context is missing, the safe state is unavailable or
quarantined—not an implied permission or a fabricated relationship.
