import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthProvider, useAuth } from '@shiki/features/auth';
import { ThemeProvider } from '@shiki/hooks/use-theme';
import { NotificationProvider } from '@shiki/features/notifications';

// In local-mocked mode (default VITE_SHIKI_ENV), mock auth auto-logs in

function TestConsumer() {
  const { isAuthenticated, user } = useAuth();
  return (
    <div>
      <span data-testid="auth-status">{isAuthenticated ? 'authenticated' : 'unauthenticated'}</span>
      {user && <span data-testid="user-role">{user.role}</span>}
      {user && <span data-testid="user-name">{user.displayName}</span>}
    </div>
  );
}

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <ThemeProvider>
      <AuthProvider>
        <NotificationProvider>
          {ui}
        </NotificationProvider>
      </AuthProvider>
    </ThemeProvider>,
  );
}

describe('Auth boot flow', () => {
  it('auto-authenticates in local-mocked mode', async () => {
    renderWithProviders(<TestConsumer />);
    // In local-mocked mode, auto-login happens in useEffect
    const status = await screen.findByTestId('auth-status');
    expect(status.textContent).toBe('authenticated');
  });

  it('assigns engineering command role by default in mock mode', async () => {
    renderWithProviders(<TestConsumer />);
    const role = await screen.findByTestId('user-role');
    expect(role.textContent).toBe('shiki_engineering_command');
  });
});
