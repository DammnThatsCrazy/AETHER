import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { SolutionPackagesPage } from '@kyber/pages/packages';
import { DeploymentReadinessPage } from '@kyber/pages/deployment-readiness';

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    solutionPackages: vi.fn(async () => ({ items: [{ package_id: 'revenue_intelligence_graph', name: 'Revenue Intelligence Graph', market: ['enterprise'], readiness_status: 'sales_ready', description: 'Revenue package', buyer_personas: ['CMO'], use_cases: ['retention'], pricing_levers: ['value'], active_tenant_demand: 1, known_gaps: [] }] })),
    solutionPackage: vi.fn(async () => ({ package_id: 'revenue_intelligence_graph', name: 'Revenue Intelligence Graph', description: 'Detail', included_modules: ['Outcome Ledger'], required_feature_flags: ['decision_outcome'], recommended_integrations: ['CRM'], required_audit_exports: ['tenant_value_audit'], deployment_modes_detail: [{ name: 'standard_saas', description: 'SaaS', known_gaps: [] }], tenants_matching: [{ tenant_id: 'tenant-a', package_fit_score: 0.9 }], readiness_report: { feature_completeness: 'core', documentation_completeness: 'docs', test_coverage_status: 'tests', audit_export_support: 'available', access_control_status: 'tenant scoped', deployment_support_status: 'mapped', known_gaps: [] } })),
    deploymentReadiness: vi.fn(async () => ({ items: [{ name: 'standard_saas', readiness_status: 'sales_ready', description: 'Shared SaaS', required_controls: ['tenant isolation'], supported_features: ['audit exports'], unsupported_features: ['air-gap'], known_gaps: ['no certification claim'] }] })),
    auditExportHealth: vi.fn(async () => ({ export_volume: 2, export_success: 1, export_failure: 1, stale_or_expired_exports: 0, tenants_requesting_exports: ['tenant-a'] })),
  } } },
}));

describe('Kyber packaging pages', () => {
  it('renders Solution Packages list', async () => {
    render(<MemoryRouter><SolutionPackagesPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Revenue Intelligence Graph')).toBeInTheDocument());
    expect(screen.getByText(/tenant demand 1/i)).toBeInTheDocument();
  });

  it('renders Package Detail', async () => {
    render(<MemoryRouter initialEntries={['/packages/revenue_intelligence_graph']}><Routes><Route path="/packages/:packageId" element={<SolutionPackagesPage />} /></Routes></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Outcome Ledger')).toBeInTheDocument());
    expect(screen.getByText('tenant-a')).toBeInTheDocument();
  });

  it('renders Deployment Readiness and Audit Export Health', async () => {
    render(<MemoryRouter><DeploymentReadinessPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('standard_saas')).toBeInTheDocument());
    expect(screen.getByText(/Volume/i)).toBeInTheDocument();
  });
});
