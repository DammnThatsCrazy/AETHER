---
title: Agentic Authorization Model
slug: security/agentic-authorization-model
section: security
visibility: I
audience: [dev-senior, architect, ai]
status: experimental
since_version: "8.11.0"
source_files:
  - Backend Architecture/aether-backend/services/agentic_observability/provider_framework.py
---

# Agentic Authorization Model

Agentic authorization records store grant metadata, permission scopes, scope
hashes, approval/revocation timestamps, and `credential_ref`. They do not store
raw access tokens, refresh tokens, authorization headers, cookies, passwords,
private keys, or full credential objects.

Permission intelligence produces recommendations, not automatic revocations. The
initial findings include unused write scope, expired grant, revoked grant still
used, and scope outside an approved owner baseline.
