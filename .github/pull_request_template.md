## Summary

Describe the change.

## Product Area

- [ ] SDK
- [ ] Connector / Provider
- [ ] Ingestion
- [ ] Contracts
- [ ] Graph
- [ ] Identity
- [ ] Campaigns
- [ ] Communications
- [ ] Agents
- [ ] Value
- [ ] Risk
- [ ] 360/Lens
- [ ] UI / Frontend
- [ ] Docs
- [ ] Release
- [ ] Security
- [ ] Infra / Operations

## Source-of-Truth Updates

- [ ] `docs/source-of-truth/` updated where applicable
- [ ] Not applicable — explained below

Explanation:

## Automated Repo Consistency

This PR must pass the required **Repo Consistency** workflow. When docs,
generator inputs, or contract inputs changed, regenerate the affected derived
surfaces before running the final canonical gate:

```bash
make docs-generate
make verification-disposition BASE=<base> EXECUTE=1
make ci-check
```

The normal PR authority is `make verification-disposition BASE=<base> EXECUTE=1`;
`make ci-check` provides broad local, trusted-main, nightly, or release
evidence and includes generator-idempotency checks. This PR is not complete
until the verification disposition passes. Partial test runs
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

## Contract Impact

- [ ] No contract changes
- [ ] Contract changes included
- [ ] Validator updated
- [ ] Generated docs updated

## SDK Impact

- [ ] No SDK impact
- [ ] SDK behavior changed
- [ ] SDK docs updated
- [ ] `/v1/batch` contract preserved

## Connector Impact

- [ ] No connector impact
- [ ] Connector behavior changed
- [ ] Provider manifest updated

## Graph Impact

- [ ] No graph impact
- [ ] Projection changed
- [ ] Explainability metadata preserved

## Release Impact

- [ ] No release note needed
- [ ] Added to `CHANGELOG.md`
- [ ] Version unchanged
- [ ] Version bump included

## Repo consistency

- [ ] I ran `make docs-generate` when docs, generator inputs, or contract inputs changed
- [ ] I reviewed stale source-linked docs against their declared `source_files`, if any were reported
- [ ] I ran `make docs-generate-changed` only after reviewing affected authored docs
- [ ] I ran `make verification-disposition BASE=<base> EXECUTE=1`
- [ ] I ran `make ci-check`
- [ ] The verification disposition passes
- [ ] I recorded the broad `make ci-check` result separately
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
