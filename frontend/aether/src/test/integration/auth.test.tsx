import { beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import {
  AuthProvider,
  SESSION_EXPIRY_KEY,
  SESSION_KEY,
  SESSION_TOKEN_KEY,
  useAuth,
} from '@aether-app/features/auth';
import { ThemeProvider } from '@aether/ui';
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
