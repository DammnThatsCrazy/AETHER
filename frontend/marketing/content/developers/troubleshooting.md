---
brand: Aether
route: /developers/troubleshooting
page_type: developer-troubleshooting
status: publication-draft
seo_title: Aether troubleshooting
seo_description: Diagnose connection, ingestion, identity, and perspective issues in Aether.
primary_cta: Contact developer support
secondary_cta: Review system status
---
# Troubleshooting.
Start with the evidence path: source, consent, authentication, tenant scope,
delivery, ingestion, identity state, relationship state, and perspective
freshness.
## Common checks
- Confirm the event was emitted once with an idempotency key.
- Confirm the source timestamp, ingestion timestamp, and deployment are valid.
- Check consent, policy, and tenant scope before checking identity resolution.
- Separate a missing connection from an unresolved relationship.
- Check status and release notes before changing application code.
When escalating, include request identifiers, event names and versions,
timestamps, deployment, and the smallest reproducible example. Do not include
secrets or unnecessary personal data.
**Primary CTA:** Contact developer support
**Secondary CTA:** Review system status
