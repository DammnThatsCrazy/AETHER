---
title: Value Review
slug: kyber/value-review
section: kyber
visibility: I
audience: [exec, ops, architect]
status: stable
since_version: "8.9.0"
---

# Value Review

Value Review is the tenant-facing bridge from everyday Aether usage to renewal and EBR conversations.

## Tenant-facing contents

The page and API show observed value, expected value, pending value, recommendations acted upon, outcomes observed, top playbooks, outcome capture rate, incomplete loops, recommended next steps, setup gaps, and integration gaps.

## Isolation

All Value Review routes derive `tenant_id` from the authenticated request and never accept an arbitrary tenant selector.
