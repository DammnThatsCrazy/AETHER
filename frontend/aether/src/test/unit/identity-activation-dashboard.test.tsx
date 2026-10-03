import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';

const runtime = vi.hoisted(() => ({
  activationEnabled: true,
  queryEnabled: false,
  status: {
    tenant_id: 'tenant-a',
    historical_data_status: 'available',
    sdk_status: 'stale',
    resolution_counts: { total_entities: 3, total_aliases: 4, total_clusters: 0, recent_merges: 1, recent_splits: 0 },
    conflict_counts: { open: 0, resolved: 2, dismissed: 1 },
    projection_restatement_status: 'needs_attention',
    projection_restatement_counts: { failed: 1, queued: 2, running: 1 },
    pending_review_counts: { open: 2, approving: 0, approval_recovery_required: 1, merge_committed: 0 },
    runtime_flags: { resolution_enabled: true, projection_restatement_enabled: false },
    sdk_last_seen_at: '2026-09-26T12:00:00+00:00',
    computed_at: '2026-09-27T12:30:00+00:00',
  },
}));

vi.mock('@aether-app/features/auth', () => ({
  RequireAuth: ({ children }: { children: ReactNode }) => children,
  useAuth: () => ({ isAuthenticated: true, user: { id: 'principal-a' } }),
}));

vi.mock('@aether/ui/exploration', () => ({
  useGraphContext: () => ({ scope: { tenant_id: 'tenant-a' } }),
}));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { identity: { activationStatus: vi.fn(async () => runtime.status) } },
}));

vi.mock('@aether/ui', () => ({
  queryCache: { invalidatePrefix: vi.fn() },
  useCapabilities: () => ({ capabilities: { feature_flags: { tenant_identity_activation_dashboard_enabled: runtime.activationEnabled } } }),
  useQuery: ({ fetcher, enabled }: { fetcher: () => Promise<unknown>; enabled: boolean }) => {
    runtime.queryEnabled = enabled;
    return {
    data: runtime.status,
    isLoading: false,
    error: null,
    refetch: fetcher,
    };
  },
}));

import { TenantActivationDashboard } from '@aether-app/features/identity/TenantActivationDashboard';

describe('Tenant activation dashboard state rendering', () => {
  beforeEach(() => {
    runtime.activationEnabled = true;
    runtime.queryEnabled = false;
    runtime.status.sdk_status = 'stale';
    runtime.status.projection_restatement_status = 'needs_attention';
  });

  it('shows persisted heartbeat freshness, restatement failures, reviews, and runtime controls', () => {
    render(<TenantActivationDashboard />);

    expect(screen.getByText('stale')).toBeInTheDocument();
    expect(screen.getByText(/last SDK heartbeat was 2026-09-26T12:00/)).toBeInTheDocument();
    expect(screen.getByText('needs_attention')).toBeInTheDocument();
    expect(screen.getAllByText('1').length).toBeGreaterThan(0);
    expect(screen.getByText('Open Identity Reviews')).toBeInTheDocument();
    expect(screen.getByText('Failed Restatements')).toBeInTheDocument();
    expect(screen.getByText('Runtime Controls')).toBeInTheDocument();
    expect(screen.getByText('enabled')).toBeInTheDocument();
    expect(screen.getByText('disabled')).toBeInTheDocument();
  });

  it('uses authenticated GraphContext tenant scope and backend capability to gate the request', () => {
    render(<TenantActivationDashboard />);
    expect(runtime.queryEnabled).toBe(true);
  });

  it('does not fetch when the backend activation capability is off', () => {
    runtime.activationEnabled = false;
    render(<TenantActivationDashboard />);
    expect(screen.getByText(/dashboard is not enabled/i)).toBeInTheDocument();
    expect(runtime.queryEnabled).toBe(false);
  });
});
