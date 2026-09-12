---
title: Docs Stamping
slug: ops-docs-stamping
section: operations
visibility: I
audience: [dev-senior]
status: experimental
since_version: "0.1.0"
---

# Docs Stamping

## Overview

Aether uses a source-linked documentation model where docs declare their
source files and are validated for drift when those sources change.

## How It Works

1. Docs under `docs/` with `source_files:` frontmatter declare which
   source files they describe.
2. `source_hashes` in the frontmatter record the hash of the source
   content at the time the doc was last reviewed.
3. CI checks (`make docs-check`) detect when source files have changed
   but the doc has not been updated.

## Updating Stale Docs

When CI reports stale docs:

1. Review the source file changes.
2. Update the doc content to reflect the changes.
3. Regenerate hashes: `make docs-generate-changed`
4. Verify: `make docs-check`

## Rules

- Never blindly restamp hashes without reviewing the source changes.
- Generated docs (`docs/_generated/`) are never manually edited.
- Use `make repo-doctor-fix` to regenerate generated docs.

## Commands

| Command | Purpose |
|---|---|
| `make docs-check` | Validate doc freshness |
| `make docs-fix` | Fix doc issues |
| `make docs-generate-changed` | Regenerate only changed hashes |
| `python scripts/docs_drift.py --strict` | Strict drift check |
