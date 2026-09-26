import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { SiteProvider } from '@site/site/site-context';
import { DocsPage } from './docs-page';
import { DOCS_ORDER, DOCS_PAGES, DOCS_SECTIONS, headingIds, inlineSegments, resolveDocId, searchDocs } from './docs-model';

vi.stubEnv('VITE_SITE_OLYMPUS_URL', 'https://olympuslabsml.com');
vi.stubEnv('VITE_SITE_AETHER_URL', 'https://aether.olympuslabsml.com');

function Where() {
  return <span data-testid="where">{useLocation().pathname}</span>;
}

function renderDocs(path: string) {
  window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;
  return render(
    <SiteProvider site="aether">
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/docs" element={<DocsPage />} />
          <Route path="/docs/:page" element={<DocsPage />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </SiteProvider>,
  );
}

describe('docs content', () => {
  it('has 45 public pages, each in exactly one section', () => {
    expect(DOCS_ORDER).toHaveLength(45);
    expect(new Set(DOCS_ORDER).size).toBe(45);
    expect(Object.keys(DOCS_PAGES).sort()).toEqual([...DOCS_ORDER].sort());
  });

  it('links cards only to pages that exist', () => {
    for (const id of DOCS_ORDER) {
      for (const b of DOCS_PAGES[id]!.blocks) {
        if (b.t !== 'cards') continue;
        for (const c of b.items) if (c.link) expect(resolveDocId(c.link), `${id} → ${c.link}`).not.toBeNull();
      }
    }
  });

  it('gives every heading a unique id', () => {
    for (const id of DOCS_ORDER) {
      const ids = [...headingIds(DOCS_PAGES[id]!).values()];
      expect(new Set(ids).size, id).toBe(ids.length);
    }
  });

  it('splits inline code and resolves aliases', () => {
    expect(inlineSegments('Send to `POST /v1/batch` now')).toEqual([
      { text: 'Send to ', code: false },
      { text: 'POST /v1/batch', code: true },
      { text: ' now', code: false },
    ]);
    expect(resolveDocId('quickstart')).toBe('quickstart-web');
    expect(resolveDocId(undefined)).toBe('overview');
    expect(resolveDocId('internal-runbook')).toBeNull();
  });

  it('searches titles and body text', () => {
    expect(searchDocs('stripe').length).toBeGreaterThan(0);
    expect(searchDocs('zzzz-not-a-term')).toEqual([]);
  });
});

describe('docs page', () => {
  it('redirects /docs and aliases to canonical page URLs', () => {
    renderDocs('/docs/quickstart');
    expect(screen.getByTestId('where').textContent).toBe('/docs/quickstart-web');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(DOCS_PAGES['quickstart-web']!.title);
  });

  it('offers a skip link to a focusable main landmark', () => {
    renderDocs('/docs/overview');
    expect(screen.getByRole('link', { name: 'Skip to content' }).getAttribute('href')).toBe('#main');
    expect(screen.getByRole('main').getAttribute('tabindex')).toBe('-1');
  });

  it('shows the not-public state for unknown pages', () => {
    renderDocs('/docs/internal-runbook');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('This page is not public');
  });

  it('marks the current page in the sidebar and moves with [ and ]', async () => {
    renderDocs('/docs/overview');
    const nav = screen.getByRole('navigation', { name: 'Documentation' });
    expect(within(nav).getByRole('link', { name: 'Overview' }).getAttribute('aria-current')).toBe('page');
    await userEvent.keyboard(']');
    expect(screen.getByTestId('where').textContent).toBe(`/docs/${DOCS_ORDER[1]}`);
    await userEvent.keyboard('[[');
    expect(screen.getByTestId('where').textContent).toBe('/docs/overview');
  });

  it('switches sections from the tab bar', async () => {
    renderDocs('/docs/overview');
    const reference = DOCS_SECTIONS.find((s) => s.id === 'reference')!;
    await userEvent.click(screen.getByRole('tab', { name: new RegExp(reference.label) }));
    expect(screen.getByTestId('where').textContent).toBe(`/docs/${reference.pages[0]}`);
  });

  it('opens search with ⌘K and navigates to a result', async () => {
    renderDocs('/docs/overview');
    await userEvent.keyboard('{Meta>}k{/Meta}');
    const dialog = screen.getByRole('dialog', { name: 'Search docs' });
    await userEvent.type(within(dialog).getByRole('combobox'), 'stripe');
    const first = within(dialog).getAllByRole('option')[0]!;
    expect(first.getAttribute('aria-selected')).toBe('true');
    await userEvent.keyboard('{Enter}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByTestId('where').textContent).toMatch(/^\/docs\//);
  });

  it('keeps Tab inside the search dialog and closes it with Escape from any control', async () => {
    renderDocs('/docs/overview');
    await userEvent.keyboard('{Meta>}k{/Meta}');
    const dialog = screen.getByRole('dialog', { name: 'Search docs' });
    await userEvent.type(within(dialog).getByRole('combobox'), 'zzzz-no-match');
    const link = within(dialog).getByRole('link', { name: /Ask an engineer/ });
    await userEvent.tab();
    expect(document.activeElement).toBe(link);
    await userEvent.tab();
    expect(dialog.contains(document.activeElement)).toBe(true);
    await userEvent.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);
    link.focus();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('lands on a heading fragment instead of the top of the page', () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    renderDocs('/docs/overview#what-you-use-it-for');
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView.mock.contexts[0]).toBe(document.getElementById('what-you-use-it-for'));
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it('shows the platform version from pyproject.toml', () => {
    renderDocs('/docs/overview');
    const header = screen.getByRole('banner');
    expect(within(header).getByText(__PLATFORM_VERSION__)).toBeTruthy();
    expect(__PLATFORM_VERSION__).toMatch(/^\d+\.\d+\.\d+/);
  });
});
