---
title: Documentation Ownership Model
slug: internal/documentation-ownership
section: operations
visibility: I
audience: [dev-junior, dev-senior, ops, architect]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
---

# Documentation Ownership Model

| Information Type | Source of Truth | Enforcement |
|---|---|---|
| Platform version | `pyproject.toml` | `python scripts/bump_version.py --check` |
| Package versions | canonical platform version | `python scripts/bump_version.py --check` |
| SDK versions | canonical platform version | `python scripts/validate_sdk_release_alignment.py` |
| Native SDK constants | canonical platform version | `python scripts/validate_sdk_release_alignment.py` |
| Event names / schemas | `packages/shared/events/events.py` | `python scripts/validate_contracts.py` + generated diff check |
| Consent purposes | `packages/shared/` consent source | `python scripts/validate_contracts.py` + generated diff check |
| Environment variables | `Backend Architecture/aether-backend/config/settings.py` | `python scripts/docs_extract/extract_env.py` + generated diff check |
| Provider metadata | provider registry / source files | `python scripts/docs_extract/extract_providers.py` + generated diff check |
| Billing plans | `Backend Architecture/aether-backend/shared/plans/catalog.py` | `python scripts/docs_extract/extract_plans.py` + generated diff check |
| Capabilities | SDK source files | `python scripts/docs_extract/extract_capabilities.py` + generated diff check |
| Repo structure | tracked git files | `python scripts/sync_docs.py` + generated diff check |
| Architecture claims | authored docs with `source_files:` | `python scripts/docs_drift.py --strict` |
| Public docs metadata | docs frontmatter schema | `python scripts/validate_frontmatter.py` |

## Ownership Rules

- **Source-of-truth files own facts.**
- **Generated docs mirror facts.**
- **Authored docs explain facts.**
- **Validators enforce facts.**
- **CI blocks drift.**

If a validator catches real drift → fix the drift.  
If a validator misses real drift → improve the validator.  
Do not weaken validators to pass CI.

## Single-command validation

```bash
make repo-doctor
```

## Quick fixes

```bash
make repo-doctor-fix   # regenerate generated docs
make bump-version V=X  # update version everywhere
python scripts/docs_drift.py --update   # stamp source-linked docs after review
```
