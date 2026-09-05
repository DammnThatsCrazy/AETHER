import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AppRouter } from '@aether-marketing/app/router';
import {
  CAPABILITIES,
  CAPABILITY_SECTION_HEADINGS,
} from '@aether-marketing/content/capabilities';
import { DEVELOPER_PATHS } from '@aether-marketing/content/developer-paths';
import { findSection } from '@aether-marketing/content/sections';
import { SOLUTION_LABEL, SOLUTIONS } from '@aether-marketing/content/solutions';

/**
 * Router-level coverage for the capability-family and solution deep routes plus
 * the dedicated interactive pages (platform explorer, solutions, integrations
 * directory, developers path selector) wired in src/app/router.tsx. Every URL
 * here is an explicit route — none of these assertions depend on the `*`
 * NotFound fallback.
 */

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRouter />
    </MemoryRouter>,
  );
}

/** Deterministic first record of a content collection, guarded so the compiler
 * knows the tuple index is not undefined. */
function first<T>(list: readonly T[], name: string): T {
  const head = list[0];
  if (head === undefined) {
    throw new Error(`${name} is unexpectedly empty`);
  }
  return head;
}

describe('capability deep pages', () => {
  it('renders one capability family in its consistent form from /platform/<slug>', () => {
    const capability = first(CAPABILITIES, 'CAPABILITIES');
    renderAt(`/platform/${capability.slug}`);

    expect(
      screen.getByRole('heading', { level: 1, name: capability.title }),
    ).toBeInTheDocument();
    for (const heading of CAPABILITY_SECTION_HEADINGS) {
      expect(screen.getByRole('heading', { level: 2, name: heading })).toBeInTheDocument();
    }
    expect(screen.getByRole('link', { name: 'Back to the platform overview' })).toHaveAttribute(
      'href',
      '/platform',
    );
  });

  it('renders the capability not-found treatment for an unknown capability slug', () => {
    renderAt('/platform/definitely-not-a-family');

    expect(
      screen.getByRole('heading', { level: 1, name: /capability not found/i }),
    ).toBeInTheDocument();
  });
});

describe('solution deep pages', () => {
  it('renders one solution with its scenario label from /solutions/<slug>', () => {
    const solution = first(SOLUTIONS, 'SOLUTIONS');
    renderAt(`/solutions/${solution.slug}`);

    expect(screen.getByRole('heading', { level: 1, name: solution.title })).toBeInTheDocument();
    expect(screen.getByText(SOLUTION_LABEL)).toBeInTheDocument();
  });
});

describe('dedicated interactive section pages', () => {
  it('renders the interactive integrations directory with its hero title', () => {
    const integrations = findSection('/integrations');
    if (integrations === undefined) {
      throw new Error('SECTIONS has no /integrations entry');
    }
    renderAt('/integrations');

    expect(screen.getByRole('searchbox')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { level: 1, name: integrations.title }),
    ).toBeInTheDocument();
  });

  it('renders every developer path as a selectable form control', () => {
    renderAt('/developers');

    for (const path of DEVELOPER_PATHS) {
      expect(screen.getByRole('radio', { name: path.label })).toBeInTheDocument();
    }
  });

  it('renders the /platform family explorer linking each capability to its deep page', () => {
    const capability = first(CAPABILITIES, 'CAPABILITIES');
    renderAt('/platform');

    const link = screen.getByRole('link', { name: new RegExp(capability.shortName, 'i') });
    expect(link).toHaveAttribute('href', `/platform/${capability.slug}`);
  });
});
