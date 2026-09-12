---
title: Campaign Resolution Architecture
slug: campaign-resolution
section: architecture
visibility: I
audience: [dev-senior, architect]
status: experimental
since_version: "0.1.0"
---

# Campaign Resolution Architecture

## Overview

Campaign resolution maps incoming observations to their originating
campaigns, preserving the distinction between source classification
and campaign identity.

## Core Invariant

Source classification is not campaign identity. An observation may arrive
from a particular SDK source or provider without belonging to any campaign,
and a single campaign may span multiple sources.

## Resolution Flow

```
observation with source metadata
→ campaign key extraction (UTM, referral, provider campaign ID)
→ campaign lookup / creation
→ touchpoint attribution (not credit assignment)
→ graph projection as campaign-entity edge
```

## Attribution Model

- Touchpoints record that an entity interacted with a campaign.
- Journey touchpoints are not attribution credits.
- Attribution basis is explicit: `direct`, `temporal`, `probabilistic`,
  `benchmark_only`, or `insufficient_evidence`.
- Credit assignment is a downstream analytics concern, not a resolution
  concern.

## Current State

Campaign resolution is implemented in
`Backend Architecture/aether-backend/services/campaigns/`.
