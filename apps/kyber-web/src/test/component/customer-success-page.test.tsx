import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { CustomerSuccessPage } from '@kyber/pages/customer-success';

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    customerSuccessOverview: vi.fn(async () => ({ total_customers: 1, active_customers: 1, value_proven_customers: 1, expansion_ready_customers: 1, at_risk_customers: 0, open_triggers: 2, open_renewal_risks: 0, open_expansion_opportunities: 1, estimated_expansion_pipeline: 5000 })),
    customerSuccessAccounts: vi.fn(async () => ({ items: [{ tenant_id: 'tenant-a', account_name: 'Acme', plan_tier: 'enterprise', lifecycle_stage: 'value_proven', health_score: 0.9, expansion_score: 0.8, renewal_risk_score: 0.1, observed_value_total: 10000, outcome_capture_rate: 1, playbook_adoption_rate: 1, integration_adoption_rate: 1, next_recommended_action: 'Prepare EBR' }] })),
    expansionOpportunities: vi.fn(async () => ({ items: [{ opportunity_id: 'op-1', tenant_id: 'tenant-a', opportunity_type: 'enterprise_upgrade', next_step: 'Propose enterprise modules', confidence: 0.8 }] })),
    renewalRisks: vi.fn(async () => ({ items: [{ renewal_risk_id: 'risk-1', tenant_id: 'tenant-a', primary_failure_mode: 'low_outcome_capture', recommended_intervention: 'Capture outcomes' }] })),
    generateEbr: vi.fn(async () => ({ value_created_summary: { observed_value_total: 10000 }, outcome_ledger_summary: { outcomes_observed: 3 }, playbook_roi_summary: { playbook_adoption_rate: 1 }, usage_summary: { recommendations_generated: 4 }, integration_summary: { integration_adoption_rate: 1 }, recommended_next_modules: ['decision_intelligence_pro'], next_90_day_plan: ['Capture outcomes'] })),
    accountPlan: vi.fn(async () => ({ current_package_id: 'starter', target_package_id: 'enterprise', strategic_objectives: ['prove value'], success_criteria: ['ROI'], risks: ['sponsor gap'], opportunities: ['module expansion'], next_actions: [] })),
    customerSuccessTriggersGenerate: vi.fn(async () => ({ count: 1 })),
  } } },
}));

describe('Customer Success Command Center', () => {
  it('renders overview, tenant health table, feeds, EBR builder, and account plan detail', async () => {
    render(<MemoryRouter><CustomerSuccessPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Customer Success Command Center')).toBeInTheDocument());
    expect(screen.getByText('Tenant Health Table')).toBeInTheDocument();
    expect(screen.getByText('Expansion Opportunity Feed')).toBeInTheDocument();
    expect(screen.getByText('Renewal Risk Feed')).toBeInTheDocument();
    expect(screen.getByText('EBR Builder')).toBeInTheDocument();
    expect(screen.getByText('Account Plan Detail')).toBeInTheDocument();
    expect(screen.getAllByText('Acme').length).toBeGreaterThan(0);
  });
});
