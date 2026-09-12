---
title: CI/CD Operations
slug: ops-ci-cd
section: operations
visibility: I
audience: [dev-senior, ops]
status: experimental
since_version: "0.1.0"
---

# CI/CD Operations

## Overview

Aether uses a verification router to determine which checks run for a
given change, based on the files modified and the lane selected.

## Verification Lanes

| Lane | Purpose | Checks |
|---|---|---|
| fast | Quick validation for config/toolchain changes | toolchain, metadata, inventory |
| pr | Standard PR gate | fast + contracts |
| integration | Integration testing | pr + integration suite |
| regression | Full regression | integration + full test suite |
| release | Release gate | regression + release checks |

## Verification Authority

```bash
make verification-disposition BASE=<ref> EXECUTE=1
```

This is the single blocking authority for a normal PR. The broad `make
ci-check` command remains available for local, trusted-main, nightly, and
release evidence; it is not a second blocking normal-PR status.

## Check Ownership

| Check | Owner | Risk |
|---|---|---|
| toolchain | platform | critical |
| contracts | platform | critical |
| impact_graph | platform | critical |
| docs | docs | high |
| integration | platform | high |
| regression | quality | high |
| release | release | critical |

## Configuration

- `config/verification_router.yaml` — check definitions and lane assignments
- `config/ci_runtime_budgets.yaml` — runtime budget enforcement
- `config/impact_graph.json` — path-to-component mapping
