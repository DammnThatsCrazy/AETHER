// Augments the *.mdx declaration from @types/mdx to include the
// `frontmatter` named export produced by remark-mdx-frontmatter
// (configured with { name: 'frontmatter' } in vite.config.ts).
//
// This file must be a TypeScript "script" (no top-level import/export)
// so it can augment the ambient module — see @types/mdx README.

declare module '*.mdx' {
  import type { DocFrontmatter } from '../lib/frontmatter';
  export const frontmatter: DocFrontmatter;
}

declare module '*.md' {
  import type { DocFrontmatter } from '../lib/frontmatter';
  export const frontmatter: DocFrontmatter;
}
