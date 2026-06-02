---
title: Implementation Lifecycle
slug: kyber/implementation-lifecycle
section: kyber
visibility: I
audience: [exec, ops, architect]
status: stable
since_version: "8.9.0"
---

# Implementation Lifecycle

The implementation lifecycle tracks required steps, blockers, success criteria, scoring, and expansion readiness for each tenant.

## Scoring

- Implementation Health Score: completed required steps, open blockers, SDK status, event mapping health, graph activation, recommendation readiness, playbook readiness, integration readiness, and outcome readiness.
- Go-Live Readiness Score: SDK live, required events, identity verification, graph active, recommendations enabled, required playbooks, integrations, and audit exports where applicable.
- Value Readiness Score: generated/viewed recommendations, decision records, actions, outcomes, populated ledger, and success criteria.
- Expansion Readiness Score: value proven, outcome capture rate, playbook ROI, integration adoption, observed value, package-fit signals, and low blocker count.

## Deployment-Mode-Specific Onboarding

Deployment mode is stored on the implementation plan and should tune audit, integration, security, and go-live approval expectations for SaaS, private cloud, VPC, and government planning deployments.

## Governance

Tenant routes remain tenant-scoped. Olympus-owned steps cannot be completed by tenants. Kyber write routes require admin permission.
