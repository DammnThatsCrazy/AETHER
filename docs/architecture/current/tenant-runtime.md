---
title: "Tenant Runtime"
slug: architecture/current/tenant-runtime
section: architecture
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Tenant Runtime

## Purpose

The tenant runtime manages activation, readiness, plan limits, entitlements, and health for each tenant.

## Components

- Tenant activation spine
- Plan and entitlement management
- Usage metering
- Health monitoring
- Feature flags and rollout controls

## Current State

Tenant runtime is in active development. Activation spine and plan management are functional. Production-grade metering and self-service onboarding are converging.
