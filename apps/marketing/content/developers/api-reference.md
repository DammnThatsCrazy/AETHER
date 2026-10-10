---
brand: Aether
route: /developers/api-reference
page_type: developer-api-reference
status: publication-draft
seo_title: Aether API reference
seo_description: Public API reference entry point for Aether connection, relationship, and perspective surfaces.
primary_cta: Open the API documentation
secondary_cta: Review security and privacy
---
# API reference.
The API surface is organized around connections, observations, relationship
state, perspectives, governance, and operational verification.
## Reference conventions
Every request is tenant-scoped and authenticated. Payloads should identify
provenance, version, idempotency, and consent or policy context where relevant.
Responses distinguish observed, resolved, inferred, unavailable, and review-
required states.
## Production expectations
Use server-side credentials, implement retries with bounded backoff, record
request identifiers, and monitor freshness and failure rates. Treat the API as
one access path into the suite rather than as a replacement for connectors,
imports, or first-party SDKs.
**Primary CTA:** Open the API documentation
**Secondary CTA:** Review security and privacy
