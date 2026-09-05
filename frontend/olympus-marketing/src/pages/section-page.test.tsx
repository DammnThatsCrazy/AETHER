import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { SectionPage } from './section-page';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="company" element={<SectionPage />} />
        <Route path="products" element={<SectionPage />} />
        <Route path="products/aether" element={<SectionPage />} />
        <Route path="contact" element={<SectionPage />} />
        <Route path="legal" element={<SectionPage />} />
        <Route path="careers" element={<SectionPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('SectionPage', () => {
  it('renders an internal cta from section copy and drops the generic fallback band', () => {
    const { unmount } = renderAt('/products');

    const link = screen.getByRole('link', { name: 'Read about Aether' });
    expect(link).toHaveAttribute('href', '/products/aether');
    expect(screen.queryByText('Explore the platform Olympus Labs builds.')).toBeNull();
    unmount();
  });

  it('renders the real support channels and frames the status page as planned on the contact page', () => {
    const { unmount } = renderAt('/contact');

    expect(screen.getByRole('link', { name: /Documentation and support/ })).toHaveAttribute(
      'href',
      'https://docs.olympuslabs.com',
    );
    // The status origin is a planned surface (deploy contract §7); marketing
    // must not present it as live, so no status link is rendered.
    expect(screen.queryByRole('link', { name: /Service status/ })).toBeNull();
    expect(screen.getByText(/public status page for the Aether platform is in planning/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Product sign-in/ })).toHaveAttribute('href', 'https://app.olympuslabs.com');

    const explore = screen.getByRole('link', { name: 'Explore Aether' });
    expect(explore).toHaveAttribute('href', 'https://aether.olympuslabs.com');
    expect(explore).toHaveAttribute('target', '_blank');
    expect(explore).toHaveAttribute('rel', 'noreferrer');
    unmount();
  });

  it('suppresses the CTA band and links trust surfaces (status framed as planned) on the legal page', () => {
    const { unmount } = renderAt('/legal');

    expect(screen.queryByText('Explore the platform Olympus Labs builds.')).toBeNull();
    expect(screen.queryByRole('link', { name: 'Explore Aether' })).toBeNull();
    expect(screen.queryByRole('link', { name: /Service status/ })).toBeNull();
    expect(screen.getByText(/a public status page for the platform is in planning/i)).toBeInTheDocument();
    unmount();
  });

  it('keeps the generic fallback band for sections without their own cta', () => {
    const { unmount } = renderAt('/company');

    expect(screen.getByText('Explore the platform Olympus Labs builds.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Explore Aether' })).toHaveAttribute('href', 'https://aether.olympuslabs.com');
    expect(screen.getByRole('link', { name: 'Contact Olympus Labs' })).toHaveAttribute('href', '/contact');
    unmount();
  });

  it('ships finished prose with no build-state scaffolding', () => {
    const { unmount } = renderAt('/careers');

    expect(screen.queryByText(/phase 2/i)).toBeNull();
    expect(screen.getByText(/open roles are shared on this page when they are posted/i)).toBeInTheDocument();
    unmount();
  });
});
