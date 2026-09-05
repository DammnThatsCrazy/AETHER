import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';
import { AppRouter } from '@aether-marketing/app/router';
import { AETHER_DOCS_URL, AETHER_MARKETING_URL } from '@aether-marketing/lib/env';

function content(selector: string): string | null {
  return document.head.querySelector(selector)?.getAttribute('content') ?? null;
}

function canonical(): string | null {
  return document.head.querySelector('link[rel="canonical"]')?.getAttribute('href') ?? null;
}

function countManaged(key: string): number {
  return document.head.querySelectorAll(`[data-meta-key="${key}"]`).length;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRouter />
    </MemoryRouter>,
  );
}

describe('per-route head meta', () => {
  beforeEach(() => {
    document.head.querySelectorAll('[data-meta-key]').forEach((el) => el.remove());
    document.title = '';
  });

  it('sets the full home head: title, description, robots, canonical, and social tags', () => {
    renderAt('/');

    expect(document.title).toBe('Aether — Relationship intelligence by Olympus Labs');
    expect(content('meta[name="description"]')).toContain('governed graph');
    expect(content('meta[name="robots"]')).toBe('index,follow');
    expect(canonical()).toBe(`${AETHER_MARKETING_URL}/`);
    expect(content('meta[property="og:type"]')).toBe('website');
    expect(content('meta[property="og:site_name"]')).toBe('Aether by Olympus Labs');
    expect(content('meta[property="og:url"]')).toBe(`${AETHER_MARKETING_URL}/`);
    expect(content('meta[property="og:title"]')).toBe('Aether — Relationship intelligence by Olympus Labs');
    expect(content('meta[name="twitter:card"]')).toBe('summary');
    expect(content('meta[name="twitter:title"]')).toBe('Aether — Relationship intelligence by Olympus Labs');
    expect(content('meta[property="og:description"]')).not.toBeNull();
  });

  it('derives the canonical and title per section route', () => {
    renderAt('/platform');

    expect(canonical()).toBe(`${AETHER_MARKETING_URL}/platform`);
    expect(content('meta[name="robots"]')).toBe('index,follow');
    expect(content('meta[property="og:title"]')).toBe(
      'One governed graph across the activity that shapes outcomes — Aether by Olympus Labs',
    );
  });

  it('marks authentication threshold routes noindex with a marketing-root canonical', () => {
    renderAt('/login');

    expect(content('meta[name="robots"]')).toBe('noindex,nofollow');
    expect(canonical()).toBe(`${AETHER_MARKETING_URL}/`);
    expect(content('meta[property="og:title"]')).toBe('Sign in — Aether by Olympus Labs');
  });

  it('updates tags in place on route change without duplicating and never leaves a stale noindex', async () => {
    const view = renderAt('/login');
    expect(content('meta[name="robots"]')).toBe('noindex,nofollow');

    fireEvent.click(screen.getByRole('link', { name: 'Back to the Aether home page' }));
    await screen.findByRole('heading', { name: /one governed graph/i });

    expect(canonical()).toBe(`${AETHER_MARKETING_URL}/`);
    expect(content('meta[name="robots"]')).toBe('index,follow');
    expect(countManaged('canonical')).toBe(1);
    expect(countManaged('robots')).toBe(1);

    view.unmount();
  });

  it('removes the tags it created on unmount', () => {
    const view = renderAt('/platform');
    expect(canonical()).not.toBeNull();
    expect(content('meta[name="robots"]')).not.toBeNull();

    view.unmount();

    expect(document.head.querySelector('link[rel="canonical"]')).toBeNull();
    expect(document.head.querySelector('meta[name="robots"]')).toBeNull();
    expect(document.head.querySelector('[data-meta-key="og:title"]')).toBeNull();
    expect(document.head.querySelector('[data-meta-key="description"]')).toBeNull();
  });

  it('opens an external section CTA in a new tab with noreferrer and keeps internal CTAs in the router', () => {
    renderAt('/developers');
    const main = within(screen.getByRole('main'));
    const docsCta = main.getByRole('link', { name: 'Read the technical documentation' });
    expect(docsCta).toHaveAttribute('href', AETHER_DOCS_URL);
    expect(docsCta).toHaveAttribute('target', '_blank');
    expect(docsCta).toHaveAttribute('rel', 'noreferrer');
  });

  it('keeps the default fallback band for sections without a custom CTA and suppresses the platform self-link', () => {
    renderAt('/platform');
    const main = within(screen.getByRole('main'));
    const primary = main.getByRole('link', { name: 'Start building' });
    expect(primary).toHaveAttribute('href', '/signup');
    expect(primary).not.toHaveAttribute('target');
    expect(primary).not.toHaveAttribute('rel');
    expect(main.queryByRole('link', { name: 'Explore the platform' })).toBeNull();
  });
});
