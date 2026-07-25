import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { MePage } from '@aether-app/pages/me/me-page';

const state = vi.hoisted(() => ({
  profile: {} as Record<string, unknown>,
  usage: {} as Record<string, unknown>,
}));

vi.mock('@aether-app/features/account', () => ({
  useMeProfile: () => state.profile,
  useUsage: () => state.usage,
}));

vi.mock('@aether-app/features/auth', () => ({
  useAuth: () => ({ logout: vi.fn() }),
}));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { me: { deleteAccount: vi.fn() } },
}));

const profile = {
  tenant_id: 'tenant-real',
  name: 'Backend Tenant',
  contact_email: 'owner@example.test',
  plan: { plan_id: 'P1', display_name: 'Starter', monthly_quota: 1000, burst_rpm: 10 },
  billing: { subscription_status: 'active', current_period_end: null },
  api_key_count: 0,
  is_admin: true,
};

function renderPage() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter><MePage /></MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

describe('Me route data-truth states', () => {
  beforeEach(() => {
    state.profile = { data: profile, isLoading: false, error: null, refetch: vi.fn() };
    state.usage = { data: null, isLoading: false, error: null, refetch: vi.fn() };
  });

  it('renders loading without account or usage conclusions', () => {
    state.profile = { data: null, isLoading: true, error: null, refetch: vi.fn() };
    renderPage();
    expect(document.querySelector('.animate-pulse')).not.toBeNull();
    expect(screen.queryByText('Backend Tenant')).not.toBeInTheDocument();
  });

  it('renders profile failure as unavailable', () => {
    state.profile = { data: null, isLoading: false, error: 'backend offline', refetch: vi.fn() };
    renderPage();
    expect(screen.getByText('Failed to load profile')).toBeInTheDocument();
  });

  it('renders missing measured usage as empty, not authoritative zero', () => {
    renderPage();
    expect(screen.getByText('Usage has not been measured for this billing period.')).toBeInTheDocument();
    expect(screen.queryByText('0 events', { exact: true })).not.toBeInTheDocument();
  });

  it('renders usage failure separately from measured usage', () => {
    state.usage = { data: null, isLoading: false, error: 'usage service unavailable', refetch: vi.fn() };
    renderPage();
    expect(screen.getByText('Usage data unavailable')).toBeInTheDocument();
    expect(screen.queryByText(/quota limits shown/i)).not.toBeInTheDocument();
  });

  it('renders backend-measured populated usage', () => {
    state.usage = {
      data: {
        period_start: '2026-07-01T00:00:00Z',
        period_end: '2026-08-01T00:00:00Z',
        events_used: 12,
        events_quota: 1000,
        rpm_peak: 3,
        rpm_limit: 10,
        overage_events: 0,
        days_remaining: 7,
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    renderPage();
    expect(screen.getByText('Backend Tenant')).toBeInTheDocument();
    expect(screen.getByText('7 days remaining')).toBeInTheDocument();
  });
});
