---
title: Tenant Setup
slug: tenant-setup
section: developer
visibility: P
audience: [dev-junior, dev-senior]
status: experimental
since_version: 0.1.0
---

# Tenant Setup

Aether is a multi-tenant platform. Each tenant has an isolated
intelligence graph, configuration, and access controls.

## Create a Tenant

Tenant creation is currently an administrative operation. Contact your
Aether administrator or use the staging environment for development.

## Configure API Keys

Each tenant has one or more API keys for SDK and API authentication.

## Tenant Configuration

| Setting | Description | Default |
|---|---|---|
| `identity_merge_rules` | Controls identity resolution behavior | Deterministic only |
| `consent_purposes` | Active consent purposes | All 12 purposes |
| `region_policy` | Data residency constraints | No restrictions |
| `sdk_allowed_event_types` | Event types accepted from SDKs | All canonical types |

## Environment Mapping

| Environment | Purpose |
|---|---|
| Local | Developer workstation testing |
| Staging | Integration testing with production-like config |
| Production | Live tenant data (not yet available) |

## Next Steps

See [Local Development](./local-development.md) for setting up a local
development environment.
