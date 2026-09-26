import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { App } from '@site/app/app';
import { RELATIONSHIP_TYPES } from '@site/components/relationship-explorer';

vi.stubEnv('VITE_SITE_OLYMPUS_URL', 'https://olympuslabsml.com');
vi.stubEnv('VITE_SITE_AETHER_URL', 'https://aether.olympuslabsml.com');

function renderHome() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <App site="olympus" />
    </MemoryRouter>,
  );
}

const tabs = () => within(screen.getByRole('tablist', { name: 'Olympus Labs' }));

describe('Olympus Home', () => {
  beforeEach(() => {
    vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    window.location.hash = '';
  });

  it('renders the hero and sets the document title', () => {
    renderHome();
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(
      'Intelligence infrastructure for human and agentic economies.',
    );
    expect(document.title).toContain('Olympus Labs');
  });

  it('opens on the Company tab and switches panels', async () => {
    renderHome();
    expect(tabs().getByRole('tab', { name: /Company/ }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('tabpanel').id).toBe('panel-company');

    await userEvent.click(tabs().getByRole('tab', { name: /Principles/ }));
    expect(screen.getByRole('tabpanel').id).toBe('panel-principles');
    expect(screen.getByText('Operational trust is foundational infrastructure.')).toBeTruthy();
  });

  it('selects a tab from the URL hash, as header links like /#contact do', () => {
    window.location.hash = '#contact';
    renderHome();
    expect(screen.getByRole('tabpanel').id).toBe('panel-contact');

    act(() => {
      window.location.hash = '#research';
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
    expect(screen.getByRole('tabpanel').id).toBe('panel-research');
    expect(window.scrollTo).toHaveBeenCalled();
  });

  it('expands one research question at a time', async () => {
    window.location.hash = '#research';
    renderHome();
    const card = screen.getByRole('button', { name: /Identity continuity/ });
    expect(card.getAttribute('aria-expanded')).toBe('false');
    await userEvent.click(card);
    expect(card.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText(/When does evidence justify joining two records/)).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: /Temporal journeys/ }));
    expect(card.getAttribute('aria-expanded')).toBe('false');
  });

  it('routes contact cards to the same-site contact page with a type', () => {
    window.location.hash = '#contact';
    renderHome();
    const panel = screen.getByRole('tabpanel');
    expect(within(panel).getByRole('link', { name: /Start a pilot/ }).getAttribute('href')).toBe('/contact?type=pilot');
    expect(within(panel).getByRole('link', { name: /Security review/ }).getAttribute('href')).toBe(
      '/contact?type=security',
    );
  });

  it('links to Aether with absolute cross-site URLs', () => {
    renderHome();
    const main = screen.getByRole('main');
    const aetherLinks = within(main)
      .getAllByRole('link')
      .map((a) => a.getAttribute('href') ?? '')
      .filter((h) => h.includes('aether.olympuslabsml.com'));
    expect(aetherLinks).toContain('https://aether.olympuslabsml.com/');
    expect(aetherLinks).toContain('https://aether.olympuslabsml.com/docs');
  });

  it('shows the connector catalog with registry marks', async () => {
    renderHome();
    await userEvent.click(screen.getByRole('tab', { name: /Connected systems/ }));
    expect(screen.getByText('13 managed connectors, plus any system you can reach')).toBeTruthy();
    expect(screen.getByText('HubSpot')).toBeTruthy();
    // Third-party logos wait for legal review; the registry shows initials.
    expect(document.querySelectorAll('#panel-company [data-provider]').length).toBeGreaterThanOrEqual(13);
    expect(document.querySelector('#panel-company [data-provider="hubspot"]')?.textContent).toBe('H');
  });
});

describe('Relationship explorer', () => {
  it('defaults to human-to-agent and switches type', async () => {
    renderHome();
    const list = screen.getByRole('tablist', { name: 'Relationship types' });
    expect(within(list).getByRole('tab', { name: /Human to agent/ }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByText(RELATIONSHIP_TYPES[1]!.value)).toBeTruthy();

    await userEvent.click(within(list).getByRole('tab', { name: /Agent to human/ }));
    expect(screen.getByText(RELATIONSHIP_TYPES[3]!.value)).toBeTruthy();
  });
});
