/**
 * Trust-plane session login flow.
 *
 * The backend returns a durable session grant when HUMAN_SESSIONS_ENABLED is
 * on, or a legacy api_key when it is off. The login page must authenticate
 * with either shape: the session token is stored (and the legacy key slot
 * cleared) under trust-plane, and the legacy key path keeps working when the
 * flag is off.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import {
  AuthProvider,
  SESSION_KEY,
  SESSION_TOKEN_KEY,
  SESSION_EXPIRY_KEY,
} from '@aether-app/features/auth';
import { LoginPage } from '@aether-app/pages/login/login-page';
import { api } from '@aether-app/lib/api/endpoints';

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { auth: { login: vi.fn() } },
}));

const loginMock = vi.mocked(api.auth.login);

const SESSION_GRANT = {
  tenant_id: 'tenant-1',
  session: {
    session_id: 'sid-1',
    token: 'sess_trustplane_token',
    credential_class: 'human_session',
    idle_expires_at: new Date(Date.now() + 60 * 60_000).toISOString(),
    absolute_expires_at: new Date(Date.now() + 12 * 60 * 60_000).toISOString(),
  },
  message: 'Authenticated. A secure session has been created.',
};

const LEGACY_GRANT = {
  tenant_id: 'tenant-1',
  api_key: 'ak_legacy_key',
  message: 'Authenticated.',
};

function renderLogin() {
  return render(
    <ThemeProvider>
      <AuthProvider>
        <MemoryRouter initialEntries={['/login']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/settings" element={<div data-testid="settings-page">settings</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </ThemeProvider>,
  );
}

async function submitCredentials() {
  fireEvent.change(screen.getByLabelText('Email address'), {
    target: { value: 'founder@tenant.dev' },
  });
  fireEvent.change(screen.getByLabelText('Password'), {
    target: { value: 'correct horse battery' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
}

describe('Login flow — trust-plane session model', () => {
  beforeEach(() => {
    sessionStorage.clear();
    loginMock.mockReset();
  });

  it('stores the session token (not an api key) for a session grant', async () => {
    loginMock.mockResolvedValue(SESSION_GRANT);
    renderLogin();
    await submitCredentials();

    await waitFor(() => {
      expect(sessionStorage.getItem(SESSION_TOKEN_KEY)).toBe('sess_trustplane_token');
    });
    expect(sessionStorage.getItem(SESSION_EXPIRY_KEY)).toBeTruthy();
    expect(sessionStorage.getItem(SESSION_KEY)).toBeNull();
    expect(await screen.findByTestId('settings-page')).toBeInTheDocument();
  });

  it('keeps the legacy api_key path working when the flag is off', async () => {
    loginMock.mockResolvedValue(LEGACY_GRANT);
    renderLogin();
    await submitCredentials();

    await waitFor(() => {
      expect(sessionStorage.getItem(SESSION_KEY)).toBe('ak_legacy_key');
    });
    expect(sessionStorage.getItem(SESSION_TOKEN_KEY)).toBeNull();
    expect(await screen.findByTestId('settings-page')).toBeInTheDocument();
  });

  it('shows the auth error when the response has no credential at all', async () => {
    loginMock.mockResolvedValue({ tenant_id: 'tenant-1' });
    renderLogin();
    await submitCredentials();

    expect(await screen.findByText('Incorrect email or password')).toBeInTheDocument();
    expect(sessionStorage.getItem(SESSION_TOKEN_KEY)).toBeNull();
    expect(sessionStorage.getItem(SESSION_KEY)).toBeNull();
  });
});
