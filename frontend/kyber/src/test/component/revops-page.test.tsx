import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { RevenueOperationsPage } from '@kyber/pages/revenue-operations';

function mockApi() {
  return {
    api: { admin: { kyber: {
      revopsOverview: vi.fn(async () => ({
        active_contracts: 12, usage_based_tenants: 5, enterprise_contract_tenants: 3, pilot_tenants: 2,
        tenants_with_overages: 1, estimated_billable_usage: 1234, value_created_total: 98765, invoice_previews_pending_review: 2,
      })),
      revopsContracts: vi.fn(async () => ({ items: [{ contract_profile_id: 'c1', tenant_id: 'tenant_alpha', package_id: 'rig', plan_tier: 'P3', billing_model: 'usage_based', billing_period: 'monthly', contract_status: 'active' }] })),
      revopsUsage: vi.fn(async () => ({ items: [] })),
      revopsInvoicePreviews: vi.fn(async () => ({ items: [] })),
      revopsValueCreated: vi.fn(async () => ({ items: [] })),
      revopsRevenueLeakage: vi.fn(async () => ({ items: [] })),
      revopsExpansionBillingOpportunities: vi.fn(async () => ({ items: [] })),
    } } },
  };
}

vi.mock('@kyber/lib/api', () => mockApi());

describe('Kyber Revenue Operations page', () => {
  it('renders the revops overview and billing table', async () => {
    render(<MemoryRouter><RevenueOperationsPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Active contracts')).toBeInTheDocument());
    expect(screen.getByText('Revenue Operations')).toBeInTheDocument();
    expect(screen.getByText('Tenant Billing Table')).toBeInTheDocument();
  });
});
