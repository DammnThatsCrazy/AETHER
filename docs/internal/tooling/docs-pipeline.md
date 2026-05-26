---
title: Documentation Pipeline
slug: tooling/docs-pipeline
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: stable
since_version: "8.8.0"
source_files:
  - scripts/validate_docs.py
  - scripts/validate_frontmatter.py
  - scripts/validate_contracts.py
  - scripts/docs_drift.py
  - scripts/sync_docs.py
  - scripts/docs_extract/run_all.py
  - scripts/docs_schema.json
  - Makefile
  - .pre-commit-config.yaml
  - .github/workflows/repo-health.yml
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
last_synced_commit: c150358
---

# Documentation Pipeline

> Internal reference for the tooling that keeps Aether's documentation
> honest. Not customer-facing.

## Why this exists

Aether's docs used to drift: a service would change behaviour and the
matching `docs/` page would silently fall out of date. The pipeline
below makes drift a build failure instead of a surprise.

Every authored page carries **YAML frontmatter** (schema:
`scripts/docs_schema.json`). Frontmatter declares the page's tier
(`visibility: P|C|I`), audience, section, and — critically — the
`source_files:` it derives from. Tooling reads that metadata to
validate, regenerate, and drift-check the corpus.

## The three tiers

`visibility:` routes every page to exactly one surface:

| Tier | Meaning | Destination |
|------|---------|-------------|
| `P` | Public | `docs.aether.network` (anonymous) |
| `C` | Customer | `portal.aether.network` (customer SSO) |
| `I` | Internal | repo only — never deployed to a site |

This page is `I`.

## Scripts

| Script | Job |
|--------|-----|
| `scripts/validate_docs.py` | Version-drift check across package manifests, changelogs, doc headers. |
| `scripts/validate_frontmatter.py` | Validates every `docs/**/*.{md,mdx}` against `docs_schema.json`. Fails on invalid **or** missing frontmatter. |
| `scripts/validate_contracts.py` | Cross-checks the generated artifacts: every event's consent purpose + family must exist in the canonical contracts. Catches cross-file drift the per-file generators can't. |
| `scripts/docs_drift.py` | For each page with `source_files:`, verifies the paths exist (fatal if not) and — when `last_synced_commit:` is set — flags staleness. `--update` re-stamps every page at HEAD. |
| `scripts/sync_docs.py` | Regenerates `docs/REPO-INDEX.md` and `docs/AUTOMATION.md` from the live tree. |
| `scripts/docs_extract/run_all.py` | Runs every generator (see below). |

## Generators

Generators live in `scripts/docs_extract/` and derive structured JSON
under `docs/_generated/` from canonical sources. Each is deterministic:
the same input yields byte-identical output, which is what makes the
drift gate reliable.

| Generator | Source | Output |
|-----------|--------|--------|
| `extract_env.py` | `.env.example` | `env.json` |
| `extract_events.py` | `packages/shared/events.ts` | `events.json` |
| `extract_consent.py` | `packages/shared/consent.ts` | `consent.json` |
| `extract_entities.py` | `packages/shared/entities.ts` | `entities.json` |
| `extract_capabilities.py` | `packages/shared/capabilities.ts` | `capabilities.json` |
| `extract_plans.py` | `shared/plans/catalog.py` | `plans.json` |
| `extract_providers.py` | `shared/providers/categories.py` | `providers.json` |
| `extract_topics.py` | `shared/events/events.py` | `topics.json` |
| `extract_doc_manifest.py` | `docs/**/*.{md,mdx}` | `doc-manifest.json` |

Adding a generator is one line in `run_all.py`'s `GENERATORS` list;
tests and the CI drift gate follow automatically.

## Make targets

```
make validate-docs        # version drift
make validate-frontmatter # frontmatter schema
make docs-drift           # source-path + staleness check
make docs-stamp           # re-stamp last_synced_commit at HEAD
make extract-docs         # regenerate docs/_generated/*.json
make docs                 # run the whole pipeline end-to-end
```

## Enforcement points

**Pre-commit** (`.pre-commit-config.yaml`) — opt-in via
`pre-commit install`. Mirrors the gates so contributors catch problems
before pushing.

**CI** (`.github/workflows/repo-health.yml`) — authoritative. On every
push and PR it runs `validate_docs`, `validate_frontmatter`,
`docs_drift`, regenerates `docs/_generated/`, and fails the build on
any uncommitted drift — the same self-healing pattern the `REPO-INDEX`
gate already used.

## Routine: changing a documented system

1. Change the code.
2. If you touched a canonical generator source, run `make extract-docs`
   and `git add docs/_generated/`.
3. Update the affected `docs/` page(s).
4. Run `make docs-stamp` so `last_synced_commit:` reflects the new HEAD.
5. Commit everything together.

CI rejects the PR if steps 2 or 4 were skipped.

## Known follow-ups

- `extract_openapi` and `extract_abis` generators are not yet built —
  they need a running FastAPI app and compiled Solidity respectively.
- `apps/docs/` (Phase 6) — current state:
  - Slice 1: Vite + React 19 workspace scaffold
  - Slice 2: MDX rendering via `@mdx-js/rollup` + `remark-frontmatter`
  - Slice 3: `extract_doc_manifest` generator + `DocIndex` + `DocViewer` + routing
  - Slice 4: Three build outputs (`out-public/`, `out-portal/`,
    `out-internal/`) — `VITE_TIER=P/C/I` baked at build time via
    `npm run build:public`, `build:portal`, `build:internal`
  - Upcoming: `docs/nav.config.ts` sidebar, generator-artifact pages

## Strict mode (enabled)

CI runs `python scripts/docs_drift.py --strict`. Any commit that
touches a path listed in a doc's `source_files:` without also bumping
that doc's `last_synced_commit:` will fail the build.

Two ways to remediate:

1. **The change updates the doc's content.** Edit the doc, then run
   `make docs-stamp` (or call `python scripts/docs_drift.py --update`
   yourself) and commit the new `last_synced_commit:` value.

2. **The change is incidental — the doc is still accurate.** Run
   `make docs-stamp` to re-stamp without content edits. This is fine
   as long as you actually verified the doc still reflects reality.

Don't blanket-stamp without checking. The whole point of the gate is
to force a human eye on every change a doc claims to describe.
