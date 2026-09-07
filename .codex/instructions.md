# Documentation and Contract Stamping Protocol

Documentation is part of the repository contract surface, but source-linked
documentation is content-addressed rather than commit-addressed.

Before finalizing a change:

1. Run `make docs-check`.
2. If the drift report lists a page, inspect that page against every path in
   its `source_files:` frontmatter.
3. Update authored prose when the documented behavior changed.
4. Run `make docs-generate-changed` only after review. It updates only the
   affected `source_hashes:` markers.
5. Run `make docs-generate` when a canonical generator input or generator
   implementation changed.
6. Run `make docs-verify-idempotent` and confirm the second pass is byte-identical.
7. Run `make ci-check` before claiming completion.
8. In the PR description, explain which pages were reviewed or regenerated and
   why.

Do not solve a docs failure by blindly running a global stamp command or by
committing unrelated docs churn. A source-linked page's `source_hashes:` are
SHA-256 markers of its declared source bytes; they are not an approval and do
not replace a content review.

Generated docs are owned by their generators:

- `docs/_generated/**` — `scripts/docs_extract/run_all.py`
- `docs/REPO-INDEX.md` and `docs/AUTOMATION.md` — `scripts/sync_docs.py`

Never hand-edit those files. Global restamping or the one-time
`make docs-migrate` conversion is allowed only for an intentional docs
infrastructure change and must be isolated from feature work.
