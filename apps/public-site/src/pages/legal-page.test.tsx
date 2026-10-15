import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

  it('shows terms and switches documents from the tabs', async () => {
    renderAt('/legal/terms');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Terms and use');
    const tabs = screen.getByRole('tablist', { name: 'Legal documents' });
    expect(within(tabs).getByRole('tab', { name: 'Terms and use' })).toHaveAttribute('aria-selected', 'true');
    expect(document.getElementById('acceptable')?.textContent).toContain('Acceptable use');
    await userEvent.click(within(tabs).getByRole('tab', { name: 'Privacy and data use' }));
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Privacy and data use');
    expect(document.title).toBe('Privacy and data use — Olympus Labs');
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
