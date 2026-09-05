import { createElement } from 'react';
import type { ReactElement } from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import {
  CAPABILITIES,
  CAPABILITY_SECTION_HEADINGS,
  findCapability,
} from './capabilities';
import { findSection } from './sections';
import { CapabilityPage } from '../pages/capability-page';
import { PlatformPage } from '../pages/platform-page';

/**
 * Mount one routed page with the same route shape the integration agent will
 * wire into the app router (`/platform/:capabilitySlug`). Elements are built
 * with createElement because this data test is a `.ts` file (JSX is restricted
 * to `.tsx`).
 */
function capabilityElement(path: string): ReactElement {
  return createElement(
    MemoryRouter,
    { initialEntries: [path] },
    createElement(
      Routes,
      null,
      createElement(Route, {
        path: '/platform/:capabilitySlug',
        element: createElement(CapabilityPage),
      }),
    ),
  );
}

function renderCapability(path: string) {
  return render(capabilityElement(path));
}

function renderPlatform() {
  return render(
    createElement(
      MemoryRouter,
      { initialEntries: ['/platform'] },
      createElement(Routes, null, createElement(Route, { path: '/platform', element: createElement(PlatformPage) })),
    ),
  );
}

describe('capability copy model', () => {
  it('defines the eleven /platform families with unique kebab-case slugs', () => {
    expect(CAPABILITIES).toHaveLength(11);
    const slugs = CAPABILITIES.map((capability) => capability.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
    for (const capability of CAPABILITIES) {
      expect(capability.slug).toMatch(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);
    }
  });

  it('gives every record non-empty title, description, lead, status, and shortName', () => {
    for (const capability of CAPABILITIES) {
      expect(capability.title.trim().length).toBeGreaterThan(0);
      expect(capability.description.trim().length).toBeGreaterThan(0);
      expect(capability.lead.trim().length).toBeGreaterThan(0);
      expect(capability.status.trim().length).toBeGreaterThan(0);
      expect(capability.shortName.trim().length).toBeGreaterThan(0);
    }
  });

  it('gives every record exactly the six canonical headings in order', () => {
    expect(CAPABILITY_SECTION_HEADINGS).toHaveLength(6);
    const canonical = [...CAPABILITY_SECTION_HEADINGS];
    for (const capability of CAPABILITIES) {
      expect(capability.sections).toHaveLength(6);
      expect(capability.sections.map((section) => section.heading)).toEqual(canonical);
      for (const section of capability.sections) {
        expect(section.body.trim().length).toBeGreaterThan(0);
      }
    }
  });

  it('findCapability finds each slug and returns undefined for an unknown slug', () => {
    for (const capability of CAPABILITIES) {
      expect(findCapability(capability.slug)?.slug).toBe(capability.slug);
    }
    expect(findCapability('no-such-family')).toBeUndefined();
  });
});

describe('capability deep page', () => {
  it('renders the not-found heading for an unknown capability slug', () => {
    renderCapability('/platform/no-such-family');

    expect(screen.getByRole('heading', { level: 1, name: 'Capability not found' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to the platform overview' })).toHaveAttribute(
      'href',
      '/platform',
    );
  });

  it('renders a known capability: its title, the six canonical headings, and a link back to the platform', () => {
    const capability = findCapability('identity-resolution');
    expect(capability).toBeDefined();
    if (capability === undefined) return;

    renderCapability(`/platform/${capability.slug}`);

    expect(screen.getByRole('heading', { level: 1, name: capability.title })).toBeInTheDocument();
    for (const heading of capability.sections.map((section) => section.heading)) {
      expect(screen.getByRole('heading', { level: 2, name: heading })).toBeInTheDocument();
    }
    expect(screen.getByRole('link', { name: 'Back to the platform overview' })).toHaveAttribute(
      'href',
      '/platform',
    );
  });
});

describe('platform page', () => {
  it('renders the /platform hero title and one family-explorer card link per capability slug', () => {
    const section = findSection('/platform');
    expect(section).toBeDefined();
    if (section === undefined) return;

    renderPlatform();

    expect(screen.getByRole('heading', { level: 1, name: section.title })).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { level: 2, name: 'Explore the capability families' }),
    ).toBeInTheDocument();

    const familyLinks = screen
      .getAllByRole('link')
      .filter((link) => link.getAttribute('href')?.startsWith('/platform/'));
    expect(familyLinks).toHaveLength(CAPABILITIES.length);
    for (const capability of CAPABILITIES) {
      const expectedHref = `/platform/${capability.slug}`;
      expect(
        familyLinks.some((link) => link.getAttribute('href') === expectedHref),
      ).toBe(true);
    }
  });
});
