---
title: "ADR-0005: Documentation Source-of-Truth Policy"
slug: architecture/decisions/adr-0005-docs-source-of-truth-policy
section: architecture
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
---

# ADR-0005: Documentation Source-of-Truth Policy

## Status

Accepted

## Context

Documentation sprawl leads to conflicting information. Multiple docs describing the same concept diverge over time.

## Decision

Each major system area has one source-of-truth document under `docs/source-of-truth/`. These documents are the canonical reference. All other docs must be consistent with them.

## Consequences

- Changes to product behavior require updating the relevant source-of-truth doc
- PRs that change runtime behavior without updating docs are incomplete
- Generated docs derive from source-of-truth, not the reverse

## Enforcement

- Source-linked docs drift validation (`scripts/docs_drift.py`)
- PR template requires source-of-truth checklist
