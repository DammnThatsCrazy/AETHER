## Automated Repo Consistency

This PR must pass the required **Repo Consistency** workflow. The canonical local/cloud-agent commands are:

```bash
make docs-fix
make repo-doctor-fix
make ci-check
```

This PR is not complete until `make ci-check` passes. Partial test runs
(`npm run test:docs`, partial pytest, TypeScript-only, docs-only, or
`make repo-doctor` alone) are useful during development but are **not** sufficient
for merge readiness.

## Documentation Impact

_Describe only what changed:_

- Source behavior changed:
- Authored docs updated:
- Generated docs regenerated:
- Source-linked docs reviewed:
- Docs intentionally unchanged because:

## Repo consistency

- [ ] I ran `make docs-fix`
- [ ] I reviewed stale source-linked docs against their declared `source_files`, if any were reported
- [ ] I ran `python scripts/docs_drift.py --update` only after reviewing and updating stale authored docs
- [ ] I ran `make repo-doctor-fix`
- [ ] I ran `make ci-check`
- [ ] `make ci-check` passes
- [ ] I committed regenerated `docs/_generated/` files
- [ ] I committed synced docs: `docs/REPO-INDEX.md`, `docs/AUTOMATION.md`
- [ ] I updated package/version surfaces if `pyproject.toml` changed
- [ ] I updated the surfaces required by `docs/source-of-truth/repo_consistency_ownership.json`
- [ ] I updated source-linked docs where behavior changed
- [ ] I updated SDK public exports where package APIs changed
- [ ] I updated contract/event/consent docs if schemas changed (consent is registry-derived — no hardcoded purpose count)
- [ ] I verified no generated diff remains
- [ ] I ran `make release-gate` if this PR claims release readiness

## 360 vertical slice

Follow-up 360 projection PRs must satisfy the vertical-slice Definition-of-Done
before their registry row flips to `implemented`:
`docs/source-of-truth/INTELLIGENCE_PROJECTION_VERTICAL_SLICE_CHECKLIST.md`.

## Known Risks

*
