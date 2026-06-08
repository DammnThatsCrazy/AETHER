# Aether — Agent Repo Rules

## Before making changes

```bash
git fetch origin
git status
git rebase origin/main
```

## Before claiming completion

```bash
make repo-doctor
git status --short
```

Both must pass. Do not open a PR until `make repo-doctor` exits 0.

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
| `make ci-check` | CI-safe full path |
| `python scripts/bump_version.py --check` | Version alignment |
| `python scripts/docs_drift.py --strict` | Source-linked docs drift |
| `python scripts/validate_contracts.py` | Contract consistency |
| `python scripts/validate_sdk_release_alignment.py` | SDK alignment |
