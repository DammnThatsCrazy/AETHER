/**
 * RequireAuth deep-link continuity: an anonymous visitor hitting a guarded
 * deep link (e.g. /settings/integrations?family=google_ads&intent=connect)
 * must be bounced to /login with the FULL location preserved in `redirect` —
 * not just the pathname — so the login round-trip lands back on the same URL
 * with its query/hash intact.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom';
import { postAuthDestination, RequireAuth } from './require-auth';

const useAuthMock = vi.hoisted(() => vi.fn());

vi.mock('./auth-context', () => ({ useAuth: useAuthMock }));
vi.mock('@aether-app/components/aether-logo', () => ({
  AetherLogo: () => null,
}));

/** Renders whatever `redirect` the bounce carried (URLSearchParams decodes it,
 * so this is the destination the login page will navigate back to). */
function LoginProbe() {
  const [params] = useSearchParams();
  return <div data-testid="login-redirect">{params.get('redirect') ?? ''}</div>;
}

function renderUnauthenticated(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route
          path="/settings/integrations"
          element={
            <RequireAuth>
              <div>guarded settings</div>
            </RequireAuth>
          }
        />
        <Route
          path="/activate"
          element={
            <RequireAuth>
              <div>guarded activate</div>
            </RequireAuth>
          }
        />
        <Route
          path="/settings"
          element={
            <RequireAuth>
              <div>guarded home</div>
            </RequireAuth>
          }
        />
        <Route path="/login" element={<LoginProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('RequireAuth sign-in bounce', () => {
  beforeEach(() => {
    useAuthMock.mockReset();
  });

  it('preserves the query params of a Settings→Integrations connect deep link', async () => {
    useAuthMock.mockReturnValue({ isAuthenticated: false, isLoading: false });
    renderUnauthenticated(
      '/settings/integrations?family=google_ads&intent=connect',
    );

    await expect(screen.findByTestId('login-redirect')).resolves.toHaveTextContent(
      '/settings/integrations?family=google_ads&intent=connect',
    );
  });

  it('preserves the experience param of an activation deep link', async () => {
    useAuthMock.mockReturnValue({ isAuthenticated: false, isLoading: false });
    renderUnauthenticated(
      '/activate?experience=advertising_campaigns&intent=connect',
    );

    await expect(screen.findByTestId('login-redirect')).resolves.toHaveTextContent(
      '/activate?experience=advertising_campaigns&intent=connect',
    );
  });

  it('keeps the legacy behavior for a bare path (no query to drop)', async () => {
    useAuthMock.mockReturnValue({ isAuthenticated: false, isLoading: false });
    renderUnauthenticated('/settings');

    await expect(screen.findByTestId('login-redirect')).resolves.toHaveTextContent(
      '/settings',
    );
  });

  it('renders guarded children once authenticated', () => {
    useAuthMock.mockReturnValue({ isAuthenticated: true, isLoading: false });
    render(
      <MemoryRouter initialEntries={['/settings']}>
        <Routes>
          <Route
            path="/settings"
            element={
              <RequireAuth>
                <div>guarded home</div>
              </RequireAuth>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText('guarded home')).toBeTruthy();
  });
});

describe('postAuthDestination', () => {
  it('joins pathname, search, and hash into the post-auth destination', () => {
    expect(
      postAuthDestination({
        pathname: '/settings/integrations',
        search: '?family=google_ads&intent=connect',
        hash: '',
      }),
    ).toBe('/settings/integrations?family=google_ads&intent=connect');

    expect(
      postAuthDestination({
        pathname: '/graph',
        search: '?node=abc',
        hash: '#focus',
      }),
    ).toBe('/graph?node=abc#focus');

    expect(
      postAuthDestination({ pathname: '/settings', search: '', hash: '' }),
    ).toBe('/settings');
  });
});
