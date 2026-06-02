# Pricing Architecture

Aether pricing is structure-first. This document defines pricing levers for sales and procurement conversations without assigning dollar amounts.

## Safe claims
- Platform access can be positioned as tenant access, SDK access, base graph, base Profile360, and base intelligence feed.
- Usage dimensions are metered from existing Aether/Kyber ledgers where available.
- Premium module packaging builds on existing solution packages.

## Prohibited claims
- Do not quote prices unless an approved pricing configuration exists.
- Do not claim guaranteed ROI, guaranteed savings, or guaranteed fraud prevention.
- Do not claim certifications, authorizations, FedRAMP, StateRAMP, ATO, or self-hosted production support.

## Pricing dimensions
- Events ingested, entities resolved, graph traversals/profile queries, recommendations generated, playbook runs, action dispatches, outcomes observed, audit exports generated, integration deliveries, deployment mode, service hours, and value-created context.

## Package mapping
- Revenue Intelligence Graph: revenue, retention, recommendations, outcomes, campaign waste, integrations.
- Fraud & Risk Intelligence Graph: cases, entities, avoided-loss context, investigations, audit exports.
- Agent Governance Graph: governed agent actions, approvals, dispatches, failure-cost context.
- Operational Decision Intelligence: decisions, playbook runs, action dispatches, operational hours saved.
- Program Integrity Graph and Critical Infrastructure Coordination Graph: planning-only public-sector/regulated packaging.

## Rollout notes
Pricing is exposed in Kyber via `/v1/admin/kyber/gtm/pricing-models` and the Pricing Architecture page.
