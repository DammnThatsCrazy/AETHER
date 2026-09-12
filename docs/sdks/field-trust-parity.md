---
title: SDK Field Trust Parity
slug: field-trust-parity
section: sdks
visibility: I
audience: [dev-senior, architect]
status: experimental
since_version: "0.1.0"
---

# SDK Field Trust Parity

## Overview

Field trust parity ensures that the event field structures in
TypeScript SDK contracts match the Python backend expectations. Both
sides must agree on which fields exist, their types, and their
trust level.

## Trust Levels

| Level | Meaning |
|---|---|
| SDK-provided | Field value comes from the SDK, trusted as client input |
| Server-enriched | Field value is set by the backend during normalization |
| Derived | Field value is computed from other fields |

## Parity Enforcement

Field trust parity is validated by the CI contract suite, which
compares the TypeScript registry structure against the Python
field-trust twins.

## Registry Structure

The canonical field trust registry is defined in
`packages/shared/contracts/`. Changes to the registry require
simultaneous updates to both TypeScript and Python implementations.

## Current State

Field trust parity is enforced in CI. See the contract validation
suite for details.
