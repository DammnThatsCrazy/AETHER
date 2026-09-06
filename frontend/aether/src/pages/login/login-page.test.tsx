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
import { LoginPage, resolvePostAuthRedirect } from './login-page';

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

describe('resolvePostAuthRedirect', () => {
  it('accepts an internal deep link with query params (RequireAuth round-trip)', () => {
    expect(
      resolvePostAuthRedirect(
        '/settings/integrations?family=google_ads&intent=connect',
      ),
    ).toBe('/settings/integrations?family=google_ads&intent=connect');
  });

  it('falls back to the tenant home for empty or foreign redirect values', () => {
    expect(resolvePostAuthRedirect(null)).toBe('/settings');
    expect(resolvePostAuthRedirect('')).toBe('/settings');
    expect(resolvePostAuthRedirect('//evil.example')).toBe('/settings');
    expect(resolvePostAuthRedirect('https://evil.example')).toBe('/settings');
  });
});
