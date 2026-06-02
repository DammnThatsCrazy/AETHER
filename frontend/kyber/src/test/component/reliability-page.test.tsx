import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ReliabilityPage } from '@kyber/pages/reliability';

const overview = {
  overall_status: 'degraded',
  service_health_summary: { total: 18, healthy: 16, degraded: 1, critical: 1, unknown: 0 },
  open_incident_count: 1,
  open_incidents: [],
  slo_status: { total: 9, meeting: 8, at_risk: 1, breached: 0 },
  queue_backlog_count: 1,
  degraded_pipeline_count: 1,
  degraded_pipelines: [],
  tenant_impact: { impacted_tenant_count: 2 },
  error_budget_status: [{ slo_id: 'slo_api_availability', service_key: 'kyber_admin', status: 'at_risk', error_budget_remaining: 0.1 }],
};

function mockApi(overrides: Record<string, unknown> = {}) {
  return {
    api: { admin: { kyber: {
      reliabilityOverview: vi.fn(async () => overview),
      reliabilityServices: vi.fn(async () => ({ items: [{ service_key: 'ingestion', label: 'Event Ingestion', status: 'healthy', latency_ms: 42, open_incident_ids: [] }] })),
      reliabilityPipelines: vi.fn(async () => ({ items: [{ pipeline_key: 'sdk_to_event_store', label: 'SDK → store', source: 'sdk_gateway', destination: 'ingestion', status: 'degraded' }] })),
      reliabilityQueues: vi.fn(async () => ({ items: [{ queue_key: 'action_dispatch', label: 'Action dispatch', status: 'degraded', depth: 500 }] })),
      reliabilitySlos: vi.fn(async () => ({ items: [{ slo_id: 'slo_api_availability', service_key: 'kyber_admin', metric_key: 'availability_ratio', target: 0.999, current_value: 0.9995, status: 'meeting', error_budget_remaining: 0.5, window: '30d' }] })),
      incidents: vi.fn(async () => ({ items: [{ incident_id: 'inc-1', title: 'Ingestion degraded', severity: 'sev2', status: 'investigating', affected_services: ['ingestion'], affected_tenants: ['tenant-a'], mitigation_steps: ['scale workers'], started_at: '2026-06-01T00:00:00Z' }] })),
      runbooks: vi.fn(async () => ({ items: [{ runbook_id: 'rb_sdk_ingestion_degraded', title: 'SDK Ingestion Degraded', incident_type: 'ingestion', severity_hint: 'sev2', detection_signals: ['errors'], diagnostic_steps: ['check'], mitigation_steps: ['scale'], escalation_paths: ['on-call'] }] })),
      postmortems: vi.fn(async () => ({ items: [] })),
      ...overrides,
    } } },
  };
}

vi.mock('@kyber/lib/api', () => mockApi());

function renderPage() {
  return render(<MemoryRouter><ReliabilityPage /></MemoryRouter>);
}

describe('Reliability Command Center', () => {
  it('renders overview, service/pipeline/queue/incident/runbook/SLO views', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Reliability Command Center')).toBeInTheDocument());
    // Overview metrics
    expect(screen.getByText('Overall status')).toBeInTheDocument();
    expect(screen.getByText('Error Budget Status')).toBeInTheDocument();
    // Tab triggers present for each dashboard
    expect(screen.getByRole('tab', { name: 'Services' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Pipelines' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Queues' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Incidents' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Runbooks' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'SLOs' })).toBeInTheDocument();
  });
});
