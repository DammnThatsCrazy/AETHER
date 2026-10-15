import type { Visibility } from './frontmatter';

/**
 * The visibility tier baked into this bundle at build time.
 * Falls back to 'P' in the dev server (VITE_TIER not set → public tier).
 */
export function getBundleTier(): Visibility {
  const t = import.meta.env.VITE_TIER;
  if (t === 'C' || t === 'I') return t;
  return 'P';
}
