import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { App } from '@site/app/app';
import type { SiteId } from '@site/site/site';

vi.stubEnv('VITE_SITE_OLYMPUS_URL', 'https://olympuslabsml.com');
vi.stubEnv('VITE_SITE_AETHER_URL', 'https://aether.olympuslabsml.com');

function renderContact(site: SiteId, search = '') {
  return render(
    <MemoryRouter initialEntries={[`/contact${search}`]}>
      <App site={site} />
    </MemoryRouter>,
  );
}

async function fillValid() {
  await userEvent.type(screen.getByLabelText('Name'), 'Jordan Lee');
  await userEvent.type(screen.getByLabelText('Work email'), 'jordan@northwind.example');
  await userEvent.type(screen.getByRole('textbox', { name: /relationship question|would you like|trying to connect|review need|outcome/ }), 'One view of trial-to-paid.');
}

const jsonResponse = (status: number, body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));

describe('Contact page', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.stubEnv('VITE_API_BASE_URL', '');
  });

  it('preselects the topic from ?type= and offers Research only on Olympus', () => {
    const { unmount } = renderContact('olympus', '?type=security');
    expect((screen.getByRole('radio', { name: /Security/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole('radio', { name: /Research/ })).toBeTruthy();
    unmount();

    renderContact('aether', '?type=research');
    expect(screen.queryByRole('radio', { name: /Research/ })).toBeNull();
    expect((screen.getByRole('radio', { name: /Pilot/ }) as HTMLInputElement).checked).toBe(true);
  });

  it('marks missing fields and does not send', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test');
    renderContact('olympus');
    await userEvent.type(screen.getByLabelText('Work email'), 'jordan@');
    await userEvent.click(screen.getByRole('button', { name: /Send/ }));
    expect(screen.getByRole('alert').textContent).toContain('A few fields need attention');
    expect(screen.getByLabelText('Name').getAttribute('aria-invalid')).toBe('true');
    expect(screen.getByText('Enter a full work email.')).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('shows success only after a 2xx response, and sends the topic as lead_type', async () => {
    const fetchMock = vi.fn(() => jsonResponse(200, { data: { received: true, lead_id: '3f2a9c1e-0000-4000-8000-000000000000' } }));
    vi.stubGlobal('fetch', fetchMock);
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test/');
    renderContact('olympus', '?type=developer');
    await fillValid();
    await userEvent.click(screen.getByRole('button', { name: /Send/ }));

    const status = await screen.findByRole('status');
    expect(status.textContent).toContain('Request received');
    expect(status.textContent).toContain('lead:3f2a9c1e · routed to engineering');
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://api.example.test/v1/contact/lead');
    expect(JSON.parse(init.body as string)).toMatchObject({
      lead_type: 'developer',
      name: 'Jordan Lee',
      email: 'jordan@northwind.example',
      source: 'olympus-marketing',
    });
  });

  it('keeps the text and offers a retry when the API fails', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse(503, { error: 'unavailable' })));
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test');
    renderContact('aether');
    await fillValid();
    await userEvent.click(screen.getByRole('button', { name: /Send/ }));
    expect((await screen.findByRole('alert')).textContent).toContain('That did not go through');
    expect(screen.getByRole('button', { name: /Try again/ })).toBeTruthy();
    expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('Jordan Lee');
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('says the form is not connected when no API URL is configured', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    renderContact('aether');
    await fillValid();
    await userEvent.click(screen.getByRole('button', { name: /Send/ }));
    expect((await screen.findByRole('alert')).textContent).toContain('The form is not connected here');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
