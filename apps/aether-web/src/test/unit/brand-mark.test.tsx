import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BrandMark } from '@aether-app/components/brand-mark';

function mark(token: string, label?: string) {
  const { container } = render(<BrandMark token={token} {...(label ? { label } : {})} />);
  return container.querySelector('[data-provider-mark]') as HTMLElement;
}

describe('BrandMark', () => {
  it('renders reviewed provider marks from the canonical brand registry', () => {
    for (const family of ['shopify', 'stripe', 'hubspot', 'google_ads']) {
      const el = mark(family);
      expect(el).toHaveAttribute('data-provider-mark', 'reviewed-local');
      expect(el.querySelector('img')).not.toBeNull();
    }
  });

  it('maps the iOS SDK onto the Apple mark', () => {
    expect(mark('ios')).toHaveAttribute('data-provider-mark', 'reviewed-local');
  });

  it('falls back to neutral initials when no reviewed mark exists', () => {
    const el = mark('definitely-not-a-provider');
    expect(el).toHaveAttribute('data-provider-mark', 'fallback');
    expect(el.querySelector('img')).toBeNull();
  });
});
