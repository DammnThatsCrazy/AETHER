import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { App } from '@site/app/app';
import type { SiteId } from '@site/site/site';
import { leadUrl } from '@site/site/api';
import { pathOffered, pilotOnly, planChoicePath } from '@site/site/access';

vi.stubEnv('VITE_SITE_OLYMPUS_URL', 'https://olympuslabsml.com');
vi.stubEnv('VITE_SITE_AETHER_URL', 'https://aether.olympuslabsml.com');

function renderAt(site: SiteId, path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App site={site} />
    </MemoryRouter>,
  );
}

const linkNames = (scope: HTMLElement) => within(scope).queryAllByRole('link').map((a) => a.textContent ?? '');

describe('pilot-only access rules', () => {
  it('is off unless the build opts in', () => {
    expect(pilotOnly({})).toBe(false);
    expect(pilotOnly({ VITE_PILOT_ONLY: 'false' })).toBe(false);
    expect(pilotOnly({ VITE_PILOT_ONLY: 'true' })).toBe(true);
  });

  it('withholds only the product and status paths', () => {
    const pilot = { VITE_PILOT_ONLY: 'true' };
    for (const path of ['/app', '/app/signin', '/app/signup', '/status']) {
      expect(pathOffered(path, pilot)).toBe(false);
      expect(pathOffered(path, {})).toBe(true);
    }
    for (const path of ['/', '/pricing', '/docs', '/contact?type=pilot', '/application']) {
      expect(pathOffered(path, pilot)).toBe(true);
    }
  });

  it('sends a plan choice to checkout, or to a pilot request', () => {
    expect(planChoicePath('beta', 'annual', {})).toBe('/app/signup?plan=beta&interval=annual');
    expect(planChoicePath('beta', 'annual', { VITE_PILOT_ONLY: 'true' })).toBe('/contact?type=pilot&plan=beta');
  });

  it('posts leads to a standalone intake when one is configured', () => {
    expect(leadUrl({})).toBe('');
    expect(leadUrl({ VITE_API_BASE_URL: 'https://api.example.test/' })).toBe('https://api.example.test/v1/contact/lead');
    expect(leadUrl({ VITE_API_BASE_URL: 'https://api.example.test', VITE_LEAD_URL: ' https://intake.example.test/ ' })).toBe(
      'https://intake.example.test/',
    );
  });
});

describe('a pilot-only build', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.stubEnv('VITE_PILOT_ONLY', '');
    vi.stubEnv('VITE_LEAD_URL', '');
    vi.stubEnv('VITE_STATUS_API_URL', '');
  });

  it('offers a pilot request instead of sign-in, sign-up and status', () => {
    vi.stubEnv('VITE_PILOT_ONLY', 'true');
    renderAt('aether', '/');
    const header = screen.getByRole('banner');
    expect(linkNames(header)).not.toContain('Sign in');
    expect(within(header).getByRole('link', { name: 'Request a pilot' }).getAttribute('href')).toBe('/contact?type=pilot');
    const footer = screen.getByRole('contentinfo');
    for (const hidden of ['Sign in', 'Create an account', 'Status', 'status.olympuslabsml.com']) {
      expect(linkNames(footer)).not.toContain(hidden);
    }
    expect(screen.queryByRole('link', { name: /Create an account/ })).toBeNull();
    for (const a of screen.getAllByRole('link')) {
      expect(a.getAttribute('href') ?? '').not.toMatch(/\/app(\/|$)|\/status$/);
    }
  });

  it('keeps the full journey when the build does not opt in', () => {
    renderAt('aether', '/');
    expect(within(screen.getByRole('banner')).getByRole('link', { name: 'Sign in' }).getAttribute('href')).toBe('/app/signin');
    expect(linkNames(screen.getByRole('contentinfo'))).toEqual(expect.arrayContaining(['Sign in', 'Create an account', 'Status']));
  });

  it('turns plan choices on Pricing into pilot requests', () => {
    vi.stubEnv('VITE_PILOT_ONLY', 'true');
    renderAt('aether', '/pricing');
    const choices = screen.getAllByRole('link', { name: /^Choose / });
    expect(choices.length).toBeGreaterThan(0);
    for (const a of choices) expect(a.getAttribute('href')).toMatch(/^\/contact\?type=pilot&plan=(alpha|beta|gamma|delta)$/);
  });

  it('says status is shared with pilot partners instead of "not configured"', async () => {
    vi.stubEnv('VITE_PILOT_ONLY', 'true');
    // Production keeps its future API values; the pilot-only flag wins.
    vi.stubEnv('VITE_STATUS_API_URL', 'https://api.example.test/health');
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    renderAt('aether', '/status');
    expect(await screen.findByText('Status is shared with pilot partners')).toBeTruthy();
    expect(screen.getByText('Shared directly with pilot partners')).toBeTruthy();
    expect(screen.queryByText(/has not been connected/)).toBeNull();
    expect(screen.queryByText(/VITE_STATUS_API_URL/)).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('sends a pilot request for the chosen plan to the lead intake', async () => {
    vi.stubEnv('VITE_PILOT_ONLY', 'true');
    vi.stubEnv('VITE_LEAD_URL', 'https://intake.example.test/');
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(
        new Response(JSON.stringify({ data: { received: true, lead_id: '3f2a9c1e-0000-4000-8000-000000000000' } }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );
    vi.stubGlobal('fetch', fetchMock);
    renderAt('aether', '/contact?type=pilot&plan=beta');
    await userEvent.type(screen.getByLabelText('Name'), 'Jordan Lee');
    await userEvent.type(screen.getByLabelText('Work email'), 'jordan@northwind.example');
    await userEvent.type(screen.getByRole('textbox', { name: /relationship question|would you like|trying to connect|review need|outcome/ }), 'A pilot.');
    await userEvent.click(screen.getByRole('button', { name: /Send/ }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('https://intake.example.test/');
    const body = JSON.parse(String(init?.body));
    expect(body.lead_type).toBe('pilot');
    expect(body.use_case).toContain('Plan: Beta');
  });
});
