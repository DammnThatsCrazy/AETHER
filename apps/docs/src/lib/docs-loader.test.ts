import { describe, expect, it } from 'vitest';
import { getAvailableSlugs, getContentLoader } from './docs-loader';

describe('public documentation launch-pack loading', () => {
  it('renders imported Drive content instead of leaving it as a manifest stub', async () => {
    expect(getAvailableSlugs()).toContain('product/how-it-works');

    const loader = getContentLoader('product/how-it-works');
    expect(loader).not.toBeNull();
    if (loader === null) return;

    const page = await loader();
    expect(page.frontmatter.title).toBe('How Aether Works');
    expect(page.default).toBeTypeOf('function');
  });
});
