/**
 * Aether Docs — Phase 6 scaffold.
 *
 * Hello-world shell. This slice proves the workspace builds and routes;
 * follow-up slices add:
 *   - MDX rendering (@mdx-js/rollup + remark-frontmatter)
 *   - Doc loader that imports docs/**\/*.md(x) and filters by
 *     visibility from scripts/docs_schema.json
 *   - Three build outputs (out-public / out-portal / out-internal)
 *     routed by frontmatter `visibility:` so the same source produces
 *     three deployable bundles.
 *   - Navigation tree generated from docs/nav.config.ts (TBD).
 */
export default function App() {
  return (
    <main
      style={{
        fontFamily: 'system-ui, -apple-system, sans-serif',
        maxWidth: 720,
        margin: '4rem auto',
        padding: '0 1rem',
        lineHeight: 1.6,
      }}
    >
      <h1>Aether Docs</h1>
      <p>
        This is the scaffold for the documentation site (Phase 6 of the docs
        resolution plan). The actual rendering pipeline lands in follow-up
        slices.
      </p>
      <p>
        For now, the authored docs live under{' '}
        <code>docs/</code> in the repo, and structured artifacts under{' '}
        <code>docs/_generated/</code>. Both are kept honest by the drift
        gate enabled in <code>repo-health.yml</code>.
      </p>
    </main>
  );
}
