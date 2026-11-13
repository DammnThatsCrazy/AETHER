import { beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import {
  AuthProvider,
  SESSION_EXPIRY_KEY,
  SESSION_KEY,
  SESSION_TOKEN_KEY,
  getAccessToken,
  useAuth,
} from '@aether-app/features/auth';
import { queryCache, ThemeProvider, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { me: { profile: vi.fn() } },
}));

const profileMock = vi.mocked(api.me.profile);
const BACKEND_PROFILE = {
  tenant_id: 'tenant-from-backend',
  name: 'Verified Tenant',
  contact_email: 'verified@tenant.example',
  plan: { plan_id: 'P1', display_name: 'Hobbyist', monthly_quota: 1000, burst_rpm: 10 },
  billing: {},
  api_key_count: 1,
  is_admin: true,
  graph_scope: {
    tenant_id: 'tenant-from-backend',
    workspace_id: 'tenant-from-backend',
    environment_id: 'production',
    scope_model: 'single_workspace_tenant_v1' as const,
  },
};

function TestConsumer() {
  const { isAuthenticated, user, isLoading } = useAuth();
  return (
    <div>
      <span data-testid="loading">{isLoading ? 'loading' : 'ready'}</span>
      <span data-testid="auth-status">{isAuthenticated ? 'authenticated' : 'unauthenticated'}</span>
      {user && <span data-testid="user-email">{user.email}</span>}
      {user && <span data-testid="user-name">{user.displayName}</span>}
    </div>
  );
}

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <ThemeProvider>
      <AuthProvider>
        {ui}
      </AuthProvider>
    </ThemeProvider>,
  );
}

describe('Auth boot flow (test environment)', () => {
  beforeEach(() => {
    sessionStorage.clear();
    profileMock.mockReset();
  });

  it('does not authenticate without a backend-issued credential', async () => {
    renderWithProviders(<TestConsumer />);
    const status = await screen.findByTestId('auth-status');
    expect(status.textContent).toBe('unauthenticated');
  });

  it('does not synthesize a user identity', async () => {
    renderWithProviders(<TestConsumer />);
    await screen.findByText('unauthenticated');
    expect(screen.queryByTestId('user-email')).not.toBeInTheDocument();
    expect(screen.queryByTestId('user-name')).not.toBeInTheDocument();
  });

  it('transitions out of loading state', async () => {
    renderWithProviders(<TestConsumer />);
    const loading = await screen.findByTestId('loading');
    expect(loading.textContent).toBe('ready');
  });

  it('validates a stored session with the backend and uses only backend identity', async () => {
    sessionStorage.setItem(SESSION_TOKEN_KEY, 'sess_real_backend_token');
    sessionStorage.setItem(
      SESSION_EXPIRY_KEY,
      new Date(Date.now() + 60 * 60_000).toISOString(),
    );
    profileMock.mockResolvedValue(BACKEND_PROFILE);

    renderWithProviders(<TestConsumer />);

    expect(await screen.findByText('authenticated')).toBeInTheDocument();
    expect(screen.getByTestId('user-email')).toHaveTextContent('verified@tenant.example');
    expect(screen.getByTestId('user-name')).toHaveTextContent('Verified Tenant');
    expect(profileMock).toHaveBeenCalledOnce();
  });

  it('validates a stored API key before granting access', async () => {
    sessionStorage.setItem(SESSION_KEY, 'ak_real_backend_key');
    profileMock.mockResolvedValue(BACKEND_PROFILE);

    renderWithProviders(<TestConsumer />);

    expect(await screen.findByText('authenticated')).toBeInTheDocument();
    expect(profileMock).toHaveBeenCalledOnce();
  });

  it('rejects and clears a stored credential when backend validation fails', async () => {
    sessionStorage.setItem(SESSION_KEY, 'ak_revoked_backend_key');
    profileMock.mockRejectedValue(new Error('Unauthorized'));

    renderWithProviders(<TestConsumer />);

    expect(await screen.findByText('unauthenticated')).toBeInTheDocument();
    expect(screen.queryByTestId('user-email')).not.toBeInTheDocument();
    expect(sessionStorage.getItem(SESSION_KEY)).toBeNull();
  });

  it('does not restore a session token without a valid absolute expiry', async () => {
    sessionStorage.setItem(SESSION_TOKEN_KEY, 'sess_missing_expiry');

    renderWithProviders(<TestConsumer />);

    expect(await screen.findByText('unauthenticated')).toBeInTheDocument();
    expect(sessionStorage.getItem(SESSION_TOKEN_KEY)).toBeNull();
    expect(profileMock).not.toHaveBeenCalled();
  });
});

describe('Auth identity switches clear cached reads', () => {
  beforeEach(() => {
    sessionStorage.clear();
    profileMock.mockReset();
    profileMock.mockResolvedValue(BACKEND_PROFILE);
  });

  function SwitchConsumer({ action }: { action: 'apiKey' | 'logout' }) {
    const auth = useAuth();
    return (
      <button
        type="button"
        onClick={() => { void (action === 'apiKey' ? auth.apiKeyLogin('ak_other_tenant_key') : auth.logout()); }}
      >
        switch
      </button>
    );
  }

  it.each(['apiKey', 'logout'] as const)(
    '%s drops the previous tenant\'s cached data',
    async (action) => {
      // The query cache is module-global and its keys are not tenant-scoped,
      // so a tenant switch without a reload used to show the previous
      // tenant's communications (Codex review on DammnThatsCrazy/AETHER#867).
      queryCache.set('aether:comms:index', ['previous-tenant-campaign']);
      renderWithProviders(<SwitchConsumer action={action} />);
      (await screen.findByText('switch')).click();
      await vi.waitFor(() => expect(queryCache.get('aether:comms:index')).toBeNull());
    },
  );

  it.each(['apiKey', 'session'] as const)(
    '%s login refetches mounted queries with the new credential only',
    async (kind) => {
      // Codex review on DammnThatsCrazy/AETHER#868: clear() notifies mounted
      // queries, which refetch at once. If the new credential is not installed
      // yet, the refetch carries the previous tenant's token under the new
      // cache generation and repopulates the cache with its data.
      const tokensSeen: Array<string | null> = [];
      function Reader() {
        useQuery({
          key: 'aether:comms:index',
          fetcher: async () => { tokensSeen.push(getAccessToken()); return ['row']; },
        });
        return null;
      }
      function Login() {
        const auth = useAuth();
        const next = () => kind === 'apiKey'
          ? auth.apiKeyLogin('ak_tenant_b')
          : auth.sessionLogin({
            token: 'sess_tenant_b',
            absolute_expires_at: new Date(Date.now() + 3_600_000).toISOString(),
          } as Parameters<typeof auth.sessionLogin>[0]);
        return (
          <>
            <button type="button" onClick={() => { void auth.apiKeyLogin('ak_tenant_a'); }}>a</button>
            <button type="button" onClick={() => { void next(); }}>b</button>
          </>
        );
      }
      renderWithProviders(<><Login /><Reader /></>);
      (await screen.findByText('a')).click();
      await vi.waitFor(() => expect(getAccessToken()).toBe('ak_tenant_a'));
      await vi.waitFor(() => expect(tokensSeen).toContain('ak_tenant_a'));
      const before = tokensSeen.length;
      screen.getByText('b').click();
      const expected = kind === 'apiKey' ? 'ak_tenant_b' : 'sess_tenant_b';
      await vi.waitFor(() => expect(tokensSeen.length).toBeGreaterThan(before));
      expect(tokensSeen.slice(before)).toEqual(
        tokensSeen.slice(before).map(() => expected),
      );
    },
  );
});
