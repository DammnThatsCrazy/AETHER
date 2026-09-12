---
title: Surface Copy Rules
slug: surface-copy-rules
section: concepts
visibility: I
audience: [buyer]
status: experimental
since_version: "0.1.0"
---

# Surface Copy Rules

## Overview

Surface copy rules define the canonical language used across Aether
product surfaces (Aether, Kyber, Noesis, APIs, documentation) to
ensure consistency and accuracy.

## Core Rules

### Product Surfaces

| Surface | Usage | Never |
|---|---|---|
| Aether | Primary product UI | "Dashboard", "Analytics tool" |
| Kyber | Diagnostics and operations UI | "Admin panel", "Back office" |
| Noesis | Intelligence and insights surface | "Reports", "BI tool" |

### Technical Concepts

| Canonical Term | Never Use |
|---|---|
| Intelligence graph | "Database", "data store" |
| Observation | "Event" (alone), "tracking hit" |
| Entity | "User", "customer" (in technical context) |
| Connector | "Plugin", "integration" (as noun) |
| Provider | "Vendor", "third party" |
| Projection | "Write", "insert" |
| 360 | "Dashboard", "view" (alone) |
| Lens | "Filter", "segment" |

### Maturity Language

| State | Canonical | Never |
|---|---|---|
| Pre-production | "Pre-production", "alpha" | "Beta", "GA", "production-ready" |
| Implemented | "Current state", "implemented" | "Shipped", "released", "live" |
| Planned | "Target state", "planned" | "Coming soon", "roadmap" |

## Enforcement

Surface copy rules are enforced by the naming-truth document
(`docs/source-of-truth/naming-truth.md`) and validated during doc review.
