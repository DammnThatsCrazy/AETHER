import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { OlympusShell } from '@olympus-marketing/components/olympus-shell';

describe('OlympusShell', () => {
  it('renders the persistent Olympus Labs identity, primary navigation, and the Aether bridge', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <OlympusShell />
      </MemoryRouter>,
    );

    // Identity
    expect(screen.getByLabelText('Olympus Labs — home')).toBeInTheDocument();

    // Primary navigation (scope to the header nav — footer repeats section links)
    const primaryNav = screen.getByRole('navigation', { name: 'Primary' });
    for (const label of ['Company', 'Products', 'Research', 'Principles', 'Security']) {
      expect(within(primaryNav).getByRole('link', { name: label })).toBeInTheDocument();
    }

    // Aether bridge — Olympus marketing always links outward to Aether
    const exploreAether = screen.getByRole('link', { name: 'Explore Aether' });
    expect(exploreAether).toHaveAttribute('href', 'https://aether.olympuslabs.com');

    // Footer brand attribution
    expect(screen.getByText(/Olympus Labs builds Aether/)).toBeInTheDocument();
  });
});
