import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthProvider, useAuth } from '@kyber/features/auth';
import { ThemeProvider } from '@aether/ui';
import { NotificationProvider } from '@kyber/features/notifications';

function TestConsumer() {
  const { isAuthenticated, user, login } = useAuth();
  return (
    <div>
      <span data-testid="auth-status">{isAuthenticated ? 'authenticated' : 'unauthenticated'}</span>
      {user && <span data-testid="user-role">{user.role}</span>}
      {user && <span data-testid="user-name">{user.displayName}</span>}
      <button type="button" onClick={() => void login()}>Log in</button>
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
  it('does not auto-authenticate in the explicit test environment', async () => {
    renderWithProviders(<TestConsumer />);
    const status = await screen.findByTestId('auth-status');
    expect(status.textContent).toBe('unauthenticated');
  });

  it('fails closed when OIDC is not configured', async () => {
    const user = userEvent.setup();
    renderWithProviders(<TestConsumer />);
    await user.click(screen.getByRole('button', { name: 'Log in' }));
    expect(await screen.findByTestId('auth-status')).toHaveTextContent('unauthenticated');
  });
});
