# Documentation and Contract Stamping Protocol

Documentation is part of the repository contract surface, but source-linked
documentation is content-addressed rather than commit-addressed.

For pull requests and merge-readiness claims, follow the single canonical
workflow in `AGENTS.md`. Apply the documentation steps below only when docs,
generator inputs, contract inputs, or source-linked documentation are affected:

1. Inspect the exact source-linked pages reported by `make docs-check` against
   every path in their `source_files:` frontmatter.
2. Update authored prose when the documented behavior changed.
3. Run `make docs-generate-changed` only after review. It updates only the
   affected `source_hashes:` markers.
4. Run `make docs-generate` when a canonical generator input or generator
   implementation changed.
5. Run `make verification-disposition BASE=<base> EXECUTE=1` as the normal PR
   authority. Run `make ci-check` for broad local, trusted-main, nightly, or
   release evidence; it includes the final generator-idempotency check, so the
   standalone idempotency target is an optional diagnostic rather than a
   required duplicate.
6. In a PR description, explain which pages were reviewed or regenerated and
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
