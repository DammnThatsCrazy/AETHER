import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ImplementationPage } from '@kyber/pages/implementation';

vi.mock('@kyber/features/onboarding', () => ({
  useImplementationOverview: () => ({ loading: false, data: { count: 1, blocked_tenants: 0, go_live_readiness: 75, value_readiness: 50, expansion_readiness: 10 } }),
  useImplementationTenants: () => ({ loading: false, data: { items: [{ tenant_id: 'tenant-a', package_id: 'revenue_intelligence_graph', deployment_mode: 'saas', onboarding_stage: 'sdk_pending', implementation_health_score: 50, go_live_readiness_score: 75, value_readiness_score: 40, expansion_readiness_score: 10, blockers: 0, recommended_action: 'Advance next onboarding step' }], count: 1 } }),
  useTenantImplementation: () => ({ data: { plan: { implementation_plan_id: 'p1', tenant_id: 'tenant-a', status: 'in_progress', onboarding_stage: 'sdk_pending', required_steps: ['s1'], blockers: [], success_criteria: { required_events_received: [], minimum_event_volume: 10, graph_active: true, recommendations_generated: true, playbooks_configured: true, integrations_connected: true, outcomes_observed: true, training_completed: false, go_live_approved: false }, implementation_health_score: 50, go_live_readiness_score: 75, value_readiness_score: 40, expansion_readiness_score: 10, created_at: '', updated_at: '' }, steps: [{ step_id: 's1', tenant_id: 'tenant-a', title: 'SDK installed', description: '', category: 'sdk', status: 'completed', owner_type: 'tenant', required: true, evidence_refs: [], created_at: '', updated_at: '' }], blockers: [], customer_success_triggers: [] } }),
  useImplementationBlockers: () => ({ data: { items: [], count: 0 } }),
  useCustomerSuccessTriggers: () => ({ data: { items: [], count: 0 } }),
}));

describe('Kyber Implementation Dashboard', () => {
  it('renders dashboard, tenant detail, and trigger feed', async () => {
    render(<MemoryRouter initialEntries={['/implementation/tenant-a']}><Routes><Route path="/implementation/:tenantId" element={<ImplementationPage />} /></Routes></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Customer Implementation Dashboard')).toBeInTheDocument());
    expect(screen.getAllByText('tenant-a').length).toBeGreaterThan(0);
    expect(screen.getByTestId('tenant-implementation-detail')).toBeInTheDocument();
    expect(screen.getByTestId('customer-success-trigger-feed')).toBeInTheDocument();
  });
});
