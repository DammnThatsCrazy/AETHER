---
brand: Aether
route: /identity-resolution
page_type: capability
status: publication-draft
seo_title: Identity resolution — Aether
seo_description: Aether preserves source evidence and resolves tenant-scoped identities and relationships with confidence, uncertainty, and review states visible.
primary_cta: Read the identity model
secondary_cta: Start with a connection
---
# Resolve relationships without hiding uncertainty.
Aether keeps source evidence separate from the relationships it may support.
Identity resolution is tenant-scoped, evidence-backed, and explicit about
confidence and uncertainty.
## Preserve the path
An integration should keep the identifiers, source, timestamps, consent, and
correlation context needed to explain how two records became related. Do not
flatten every source into an anonymous event if that removes the relationship
the event was meant to explain.
## Relationship states
- **Observed:** the source asserted or emitted the record.
- **Resolved:** available evidence supports the relationship.
- **Inferred:** the relationship is a hypothesis with a confidence boundary.
- **Unavailable:** evidence or authorization is missing.
- **Review required:** a person or authorized operator must decide.
These states should remain distinguishable in APIs, graph projections, profiles,
journeys, and 360 views.
## What identity resolution is not
It is not universal identity truth, silent cross-tenant enrichment, or a reason
to erase the source records that support a relationship. Aether keeps the
evidence trail so a team can understand what was resolved and why.
**Primary CTA:** Read the identity model
**Secondary CTA:** Start with a connection
