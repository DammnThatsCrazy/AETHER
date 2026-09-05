/**
 * Public marketing shell handoff: the tenant app's /signup accepts prefilled
 * name and email carried as `?name=...&email=...`. Values are applied only as
 * the step-1 fields' initial state so the OTP flow and steps are unchanged.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { AuthProvider } from '@aether-app/features/auth';
import { SignupPage } from './signup-page';

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    auth: { register: vi.fn(), verifyEmail: vi.fn(), developmentSession: vi.fn() },
    me: { profile: vi.fn() },
  },
}));

function renderSignup(initialEntry: string) {
  return render(
    <ThemeProvider>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[initialEntry]}>
            <Routes>
              <Route path="/signup" element={<SignupPage />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </AuthProvider>
    </ThemeProvider>,
  );
}

describe('SignupPage public-handoff prefill', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('prefills name and email on step 1 from the query parameters', () => {
    renderSignup('/signup?name=Ada&email=ada%40example.com');

    expect(screen.getByLabelText('Full name')).toHaveValue('Ada');
    expect(screen.getByLabelText('Work email')).toHaveValue('ada@example.com');
  });

  it('starts step 1 with empty fields when no query parameters are present', () => {
    renderSignup('/signup');

    expect(screen.getByLabelText('Full name')).toHaveValue('');
    expect(screen.getByLabelText('Work email')).toHaveValue('');
  });
});
