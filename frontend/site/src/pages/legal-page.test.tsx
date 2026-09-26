import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { App } from '@site/app/app';

vi.stubEnv('VITE_SITE_OLYMPUS_URL', 'https://olympuslabsml.com');
vi.stubEnv('VITE_SITE_AETHER_URL', 'https://aether.olympuslabsml.com');

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <App site="aether" />
    </MemoryRouter>,
  );

describe('Legal page', () => {
  it('redirects /legal to the privacy notice', () => {
    renderAt('/legal');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Privacy and data use');
  });

  it('shows terms with numbered sections and an outline', () => {
    renderAt('/legal/terms');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Terms and use');
    const docs = screen.getByRole('navigation', { name: 'Legal documents' });
    expect(within(docs).getByRole('link', { name: /Terms and use/ }).getAttribute('aria-current')).toBe('page');
    expect(within(docs).getByRole('link', { name: /Privacy/ }).getAttribute('href')).toBe('/legal/privacy');
    const outline = screen.getByRole('navigation', { name: 'On this page' });
    expect(within(outline).getByRole('link', { name: 'Acceptable use' }).getAttribute('href')).toBe('#acceptable');
    expect(document.getElementById('acceptable')?.textContent).toContain('04');
  });

  it('states that the text is a draft and not in force', () => {
    renderAt('/legal/privacy');
    expect(screen.getByRole('note').textContent).toContain('It is not in force and is not legal advice.');
  });

  it('sends unknown documents to privacy', () => {
    renderAt('/legal/cookies');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Privacy and data use');
  });
});
