# Aether — Agent Repo Rules

Claude must follow `AGENTS.md`. This file adds Claude-specific emphasis; it does
not override it.

## Before making changes

```bash
git fetch origin
git status
git rebase origin/main
```

## Before claiming completion

The canonical completion gate is `make ci-check`.

```bash
make docs-fix
make ci-check
git status --short
```

Do not open a PR until `make ci-check` exits 0. Claude must **not** claim a PR is
complete based only on `npm test`, `npm run test`, `npm run test:docs`, partial
pytest runs, TypeScript-only checks, docs-only checks, manual inspection, or
`make repo-doctor` alone.

If source-linked docs are reported stale, update the actual docs against their
declared `source_files`, then run `python scripts/docs_drift.py --update`.
Stamping without review is not allowed.

For release readiness, also run `make release-gate` when the PR claims release
readiness.

---

## Canonical version source

`pyproject.toml` owns the platform version.  
Check: `python scripts/bump_version.py --check`  
Fix: `python scripts/bump_version.py <NEW_VERSION>`

## Generated docs rule

Docs under `docs/_generated/` and `docs/REPO-INDEX.md` / `docs/AUTOMATION.md`
are **never manually edited**.

Fix source → fix generator → regenerate → validate:

```bash
make repo-doctor-fix
make repo-doctor
```

## Source-linked docs rule

Docs with `source_files:` frontmatter must be reviewed when their linked
source files change. `last_synced_commit` is only updated **after** review:

```bash
python scripts/docs_drift.py --update
```

Never blindly stamp stale docs to silence CI.

---

## Agents must NOT

- Manually edit generated docs
- Blindly stamp source-linked docs
- Weaken validators to pass CI
- Leave generated diffs unstaged
- Skip SDK / contract / docs checks after source changes

## Agents must

- Use `make repo-doctor-fix` to regenerate docs
- Update authored docs when behavior changes
- Improve validators when they miss real drift
- Report exact failing commands if validation does not pass

---

## Quick reference

| Command | Purpose |
|---|---|
| `make repo-doctor` | Full consistency check (no mutations) |
| `make repo-doctor-fix` | Regenerate generated docs + sync |
| `make docs-check` | Docs-only fast gate |
| `make ci-check` | CI-safe full path (**canonical completion gate**) |
| `make production-status` | Readiness scorecard + blockers (advisory) |
| `make release-gate` | ci-check + strict production status + ops readiness |
| `python scripts/bump_version.py --check` | Version alignment |
| `python scripts/docs_drift.py --strict` | Source-linked docs drift |
| `python scripts/validate_contracts.py` | Contract consistency |
| `python scripts/validate_sdk_release_alignment.py` | SDK alignment |

## Production claims rule

`scripts/production_status.py` is the canonical readiness scorecard
(`docs/productization/aether_productization_audit.md` is its dated
narrative snapshot). Do not claim an area is production-ready in any doc
unless the scorecard supports it; update both together.
