/**
 * Public marketing shell handoff: the tenant app's /login accepts a prefilled
 * email carried as `?email=...`. The value is applied only as the field's
 * initial state so user typing is never clobbered by an effect.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import { AuthProvider } from '@aether-app/features/auth';
import { LoginPage } from './login-page';

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    auth: { login: vi.fn(), developmentSession: vi.fn() },
    me: { profile: vi.fn() },
  },
}));

function renderLogin(initialEntry: string) {
  return render(
    <ThemeProvider>
      <AuthProvider>
        <MemoryRouter initialEntries={[initialEntry]}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </ThemeProvider>,
  );
}

describe('LoginPage public-handoff prefill', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('prefills the email field from the ?email= query parameter', () => {
    renderLogin('/login?email=person%40example.com');

    expect(screen.getByLabelText('Email address')).toHaveValue('person@example.com');
  });

  it('leaves the email field empty when no ?email= is present', () => {
    renderLogin('/login');

    expect(screen.getByLabelText('Email address')).toHaveValue('');
  });
});
