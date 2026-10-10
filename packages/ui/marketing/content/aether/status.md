---
brand: Aether
route: /status
page_type: operations
status: publication-draft
seo_title: Aether service status
seo_description: Check Aether service availability, incidents, maintenance, and the difference between service health and provider readiness.
primary_cta: Open status
secondary_cta: Contact support
---
# Service availability and provider readiness are different.
The public status page reports service availability, incidents, maintenance, and
component health.
A service can be healthy while a tenant's selected connector, SDK fleet,
feature flag, provider credential, or deployment dependency is gated or
unavailable. The status page should separate:
- platform and API availability;
- ingestion and processing health;
- graph and perspective surfaces;
- delivery and workflow health;
- provider and connector readiness; and
- tenant-specific configuration or entitlement.
## Readiness states
- **Available:** enabled with current deployment evidence.
- **Gated:** available after configuration, credentials, or plan activation.
- **Pilot:** bounded validation in progress.
- **Unavailable:** required evidence or dependency is not present.
- **Planned:** documented direction, not a current capability.
Until the monitored status service is connected, deployment-specific state must
be confirmed through the support, product, or procurement channel.
**Primary CTA:** Open status
**Secondary CTA:** Contact support
