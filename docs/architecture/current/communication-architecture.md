---
title: Communication Architecture
slug: communication-architecture
section: architecture
visibility: I
audience: [dev-senior, architect]
status: experimental
since_version: "0.1.0"
---

# Communication Architecture

## Overview

The communication subsystem manages outbound messaging across channels
(email, SMS, push, in-app) through governed connectors, tracking delivery
state and linking communication events back to the intelligence graph.

## Architecture

```
communication intent (campaign / journey / agent trigger)
→ channel selection + consent check
→ connector dispatch (email, SMS, push providers)
→ delivery tracking (sent, delivered, opened, clicked, bounced)
→ graph projection as communication edges
```

## Key Principles

- All outbound communication flows through connectors, never direct
  provider calls from application code.
- Consent is checked at dispatch time against the tenant consent registry.
- Delivery events are observations that re-enter the ingestion pipeline.
- Communication state is projected into the graph, not stored separately.

## Current State

Communication architecture is partially implemented. See
`Backend Architecture/aether-backend/services/communications/` for the
current runtime.
