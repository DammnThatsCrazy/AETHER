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

---

## Hybrid Harness Rules (Claude Main / DeepSeek Sub-Agent)

This repo can run a hybrid harness: **Claude** is the main orchestrator/driver;
**DeepSeek** executes well-scoped, mechanical sub-tasks. DeepSeek is reached
through a local Anthropic-compatible router — never a direct base-URL swap,
because `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` are global and would send
the orchestrator to DeepSeek too. Setup, verification, and example configs live
in [`.claude/hybrid-harness/README.md`](.claude/hybrid-harness/README.md); the
executor is the `deepseek-executor` sub-agent
([`.claude/agents/deepseek-executor.md`](.claude/agents/deepseek-executor.md)).
This harness is opt-in and local: with no router running, `deepseek-executor`
simply falls back to a Claude model, so nothing here changes shared CI behavior.

- **Orchestration**: Claude (main model) owns git operations, architectural
  decisions, and ultimate task review.
- **DeepSeek sub-agent delegation**: delegate to the `deepseek-executor`
  sub-agent to handle:
  - Repetitive data parsing or migration tasks.
  - Large-scale regex refactoring across multiple files.
  - Generating boilerplate, unit tests, or basic CRUD code.
  - Scanning logs, dependency trees, or long error stack traces.
- **Prompting DeepSeek**: instruct the sub-agent with precise, mechanical,
  step-by-step constraints. Do not issue highly abstract or conceptual prompts
  to DeepSeek — give it concrete inputs, exact file paths, and a verifiable done
  condition.
- **Handoff verification**: Claude reviews every file DeepSeek modified in the
  primary environment before staging a commit. DeepSeek output is never
  committed unreviewed and never bypasses `make ci-check`.
- **Repo-safety scope**: keep DeepSeek off surfaces this repo's gates own —
  generated docs (`docs/_generated/`, `REPO-INDEX.md`, `AUTOMATION.md`),
  source-linked docs, contract registries, and the `pyproject.toml` version.
  Those stay with Claude, per the rules above.
