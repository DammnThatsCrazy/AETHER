# @aether/docs

Documentation site scaffold (Phase 6 of the docs resolution plan).

## Status

**Slice 1 — scaffold only.** This workspace builds a placeholder page.
The actual doc-rendering pipeline lands in subsequent slices.

Coming soon:

- MDX rendering via `@mdx-js/rollup`.
- Doc loader that imports `docs/**/*.md(x)` and partitions by
  `visibility:` frontmatter (`P` public · `C` customer · `I` internal).
- Three deployable build outputs (`out-public/`, `out-portal/`,
  `out-internal/`) so the same source can ship to
  `docs.aether.network`, `portal.aether.network`, or the team-only
  internal tier.
- Navigation tree generated from `docs/nav.config.ts` (also TBD).
- Pages that render the structured artifacts in `docs/_generated/`
  (event registry, env-var catalog, plans table, provider matrix, etc.).

## Local development

```bash
npm install
npm run dev    # http://localhost:5176
npm run build  # static build into dist/
```

## Architecture

```
docs/                     ← canonical authored MDX (frontmatter declares tier)
  public/                 ← visibility: P (anonymous)
  portal/                 ← visibility: C (customer SSO)
  internal/               ← visibility: I (repo-only — never deployed)
  _generated/             ← extracted JSON (env/events/plans/providers/etc.)

apps/docs/                ← this app
  src/                    ← React shell + (planned) MDX renderer
  dist/                   ← shared dev build
  out-public/             ← public bundle for docs.aether.network
  out-portal/             ← customer bundle for portal.aether.network
```

## Scripts

| Script | Purpose |
|---|---|
| `npm run dev` | Vite dev server on port 5176 |
| `npm run build` | Type-check + production build |
| `npm run typecheck` | TypeScript only |
| `npm run lint` | ESLint with autofix |
| `npm test` | Vitest |

## See also

- [Documentation Pipeline](../../docs/internal/tooling/docs-pipeline.md) —
  the validators + generators that feed this app.
- [Docs resolution plan](../../docs/internal/tooling/docs-pipeline.md) for
  the overall multi-phase roadmap.
