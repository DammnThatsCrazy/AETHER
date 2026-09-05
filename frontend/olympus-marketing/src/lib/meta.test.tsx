import { fireEvent, render, screen } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { usePageMeta, type PageMeta } from './meta';

function Probe({
  title,
  description,
  robots,
  canonical,
  children,
}: {
  readonly title: string;
  readonly description?: string;
  readonly robots?: PageMeta['robots'];
  readonly canonical?: string;
  readonly children?: ReactNode;
}) {
  usePageMeta({
    title,
    ...(description !== undefined ? { description } : {}),
    ...(robots !== undefined ? { robots } : {}),
    ...(canonical !== undefined ? { canonical } : {}),
  });
  return <>{children}</>;
}

function canonicalHref(): string | null {
  return document.querySelector<HTMLLinkElement>('link[rel="canonical"]')?.getAttribute('href') ?? null;
}

describe('usePageMeta', () => {
  it('writes title, description, canonical, and social tags for a route and removes them on unmount', () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={['/products/aether']}>
        <Probe title="Aether — Olympus Labs" description="Platform description" />
      </MemoryRouter>,
    );

    expect(document.title).toBe('Aether — Olympus Labs');
    expect(document.querySelector('meta[name="description"]')?.getAttribute('content')).toBe('Platform description');
    expect(canonicalHref()).toBe('https://olympuslabs.com/products/aether');
    expect(document.querySelectorAll('link[rel="canonical"]')).toHaveLength(1);
    expect(document.querySelector('meta[property="og:title"]')?.getAttribute('content')).toBe('Aether — Olympus Labs');
    expect(document.querySelector('meta[property="og:description"]')?.getAttribute('content')).toBe('Platform description');
    expect(document.querySelector('meta[property="og:url"]')?.getAttribute('content')).toBe('https://olympuslabs.com/products/aether');
    expect(document.querySelector('meta[property="og:type"]')?.getAttribute('content')).toBe('website');
    expect(document.querySelector('meta[property="og:site_name"]')?.getAttribute('content')).toBe('Olympus Labs');
    expect(document.querySelector('meta[name="twitter:card"]')?.getAttribute('content')).toBe('summary');
    expect(document.querySelector('meta[name="twitter:title"]')?.getAttribute('content')).toBe('Aether — Olympus Labs');

    unmount();
    expect(document.querySelectorAll('[data-olympus-meta]')).toHaveLength(0);
  });

  it('defaults the canonical to the site origin on the home route', () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={['/']}>
        <Probe title="Olympus Labs" />
      </MemoryRouter>,
    );

    expect(canonicalHref()).toBe('https://olympuslabs.com/');
    expect(document.querySelector('meta[property="og:url"]')?.getAttribute('content')).toBe('https://olympuslabs.com/');
    unmount();
  });

  it('honors a canonical override', () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={['/legal']}>
        <Probe title="Legal — Olympus Labs" canonical="https://olympuslabs.com/legal-and-trust" />
      </MemoryRouter>,
    );

    expect(canonicalHref()).toBe('https://olympuslabs.com/legal-and-trust');
    expect(document.querySelector('meta[property="og:url"]')?.getAttribute('content')).toBe('https://olympuslabs.com/legal-and-trust');
    unmount();
  });

  it('updates tags across route changes without duplication and clears a prior robots directive', () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={['/legal']}>
        <Routes>
          <Route
            path="/legal"
            element={
              <Probe title="Legal — Olympus Labs" robots="noindex,nofollow">
                <Link to="/company">Company</Link>
              </Probe>
            }
          />
          <Route path="/company" element={<Probe title="Company — Olympus Labs" description="Company copy" />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(document.querySelector('meta[name="robots"]')?.getAttribute('content')).toBe('noindex,nofollow');
    expect(canonicalHref()).toBe('https://olympuslabs.com/legal');

    fireEvent.click(screen.getByRole('link', { name: 'Company' }));

    expect(document.querySelector('meta[name="robots"]')).toBeNull();
    expect(canonicalHref()).toBe('https://olympuslabs.com/company');
    expect(document.querySelectorAll('link[rel="canonical"]')).toHaveLength(1);
    expect(document.querySelector('meta[name="description"]')?.getAttribute('content')).toBe('Company copy');
    expect(document.title).toBe('Company — Olympus Labs');
    unmount();
  });
});
