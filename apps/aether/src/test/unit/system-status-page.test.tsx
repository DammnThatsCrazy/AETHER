import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SystemStatusPage } from '@aether-app/pages/system-status';

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    status: {
      overview: vi.fn(async () => ({
        tenant_id: 'tenant-a',
        overall_status: 'degraded',
        data_freshness: 'fresh',
        active_incidents: 1,
        integration_status: 'operational',
        audit_export_status: 'operational',
        recommendation_status: 'fresh',
        outcome_capture_status: 'operational',
        updated_at: '2026-06-02T00:00:00Z',
      })),
      incidents: vi.fn(async () => ({
        active: [{ incident_id: 'inc-1', title: 'Dispatch delays', status: 'investigating', severity: 'sev2', customer_impact: 'Some actions delayed', started_at: '2026-06-01T00:00:00Z' }],
        resolved: [{ incident_id: 'inc-0', title: 'Past issue', status: 'resolved', severity: 'sev3', started_at: '2026-05-01T00:00:00Z', resolved_at: '2026-05-01T02:00:00Z' }],
      })),
    },
  },
}));

describe('Aether System Status page', () => {
  it('renders tenant-safe status, health rows, and incidents', async () => {
    render(<SystemStatusPage />);
    await waitFor(() => expect(screen.getByText('System Status')).toBeInTheDocument());
    expect(screen.getByText('Service & Data Health')).toBeInTheDocument();
    expect(screen.getByText('Data freshness')).toBeInTheDocument();
    expect(screen.getByText('Dispatch delays')).toBeInTheDocument();
    expect(screen.getByText('Some actions delayed')).toBeInTheDocument();
    expect(screen.getByText('Past issue')).toBeInTheDocument();
  });

  it('does not leak internal infrastructure terms', async () => {
    const { container } = render(<SystemStatusPage />);
    await waitFor(() => expect(screen.getByText('System Status')).toBeInTheDocument());
    const text = container.textContent ?? '';
    expect(text.toLowerCase()).not.toContain('queue');
    expect(text.toLowerCase()).not.toContain('dead-letter');
    expect(text).not.toContain('tenant-b');
  });
});
