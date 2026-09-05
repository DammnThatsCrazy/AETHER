import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { DEVELOPER_PATHS } from '@aether-marketing/content/developer-paths';
import { AETHER_DOCS_URL } from '@aether-marketing/lib/env';
import { DevelopersPage } from '@aether-marketing/pages/developers-page';

function renderDevelopersPage() {
  return render(
    <MemoryRouter initialEntries={['/developers']}>
      <DevelopersPage />
    </MemoryRouter>,
  );
}

describe('DevelopersPage', () => {
  it('renders the /developers hero from the SECTIONS entry', () => {
    renderDevelopersPage();

    expect(
      screen.getByRole('heading', { level: 1, name: 'Integrate once. Resolve everywhere.' }),
    ).toBeInTheDocument();
  });

  it('presents every developer path as a selectable radio control', () => {
    renderDevelopersPage();

    for (const path of DEVELOPER_PATHS) {
      const radio = screen.getByRole('radio', { name: path.label });
      expect(radio).toHaveAttribute('type', 'radio');
    }
    // The default path is selected on first render.
    expect(screen.getByRole('radio', { name: DEVELOPER_PATHS[0].label })).toBeChecked();
  });

  it('shows the default path panel content initially', () => {
    renderDevelopersPage();

    expect(screen.getByText(DEVELOPER_PATHS[0].description)).toBeInTheDocument();
    expect(screen.getByText(DEVELOPER_PATHS[0].state)).toBeInTheDocument();
    for (const step of DEVELOPER_PATHS[0].steps) {
      expect(screen.getByRole('heading', { level: 3, name: step.heading })).toBeInTheDocument();
      expect(screen.getByText(step.text)).toBeInTheDocument();
    }
  });

  it('swaps the visible panel when a different path is activated', () => {
    renderDevelopersPage();
    const next = DEVELOPER_PATHS[1];

    fireEvent.click(screen.getByRole('radio', { name: next.label }));

    expect(screen.getByRole('radio', { name: next.label })).toBeChecked();
    expect(screen.getByText(next.description)).toBeInTheDocument();
    expect(screen.getByText(next.state)).toBeInTheDocument();
    expect(screen.queryByText(DEVELOPER_PATHS[0].description)).not.toBeInTheDocument();
    for (const step of next.steps) {
      expect(screen.getByRole('heading', { level: 3, name: step.heading })).toBeInTheDocument();
    }
  });

  it('points at the documentation as the canonical reference and offers sign-up through the threshold', () => {
    renderDevelopersPage();

    const docsCta = screen.getByRole('link', { name: 'Read the technical documentation' });
    expect(docsCta).toHaveAttribute('href', AETHER_DOCS_URL);
    expect(docsCta).toHaveAttribute('target', '_blank');
    expect(docsCta).toHaveAttribute('rel', 'noreferrer');

    // The active path panel also links to the docs.
    expect(screen.getByRole('link', { name: 'Read the documentation' })).toHaveAttribute(
      'href',
      AETHER_DOCS_URL,
    );

    // Sign-up routes through the public /signup threshold, not the app origin.
    const startBuilding = screen.getByRole('link', { name: 'Start building' });
    expect(startBuilding).toHaveAttribute('href', '/signup');
    expect(startBuilding).not.toHaveAttribute('target');
  });

  it('still renders the /developers bullets from the SECTIONS entry', () => {
    renderDevelopersPage();

    const bulletHeadings = ['Event model', 'Identity resolution', 'Consent & governance', 'Validation'];
    for (const heading of bulletHeadings) {
      expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument();
    }
  });
});
