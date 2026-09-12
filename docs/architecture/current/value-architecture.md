---
title: Value Architecture
slug: value-architecture
section: architecture
visibility: I
audience: [dev-senior, architect]
status: experimental
since_version: "0.1.0"
---

# Value Architecture

## Overview

The value subsystem tracks monetary and non-monetary value attribution
across the intelligence graph, ensuring that missing, empty, and zero
are treated as distinct states.

## Core Invariants

- Missing, empty, and zero are distinct states.
- Value display uses canonical `ValueDisplay` / `formatUSD` paths.
- FX conversion is handled at the canonical value/FX path, never
  ad hoc in UI components.
- Attribution basis is always explicit.

## Architecture

```
value observation (transaction, conversion, revenue event)
→ Bronze normalization (currency, amount, basis)
→ Silver projection (entity value, campaign value)
→ Gold rollup (LTV, cohort value, campaign ROI)
→ 360 surface display via canonical ValueDisplay
```

## Frontend Guardrail

All monetary display in Aether and Kyber surfaces must use the canonical
`ValueDisplay` component or `formatUSD` utility. Direct formatting of
currency values is prohibited.

## Current State

Value architecture is implemented across backend services and frontend
components. See the cross-360 monetary/FX guard in the contract
validation suite.
