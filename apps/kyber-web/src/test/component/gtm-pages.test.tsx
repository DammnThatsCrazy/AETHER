import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { BuyerPersonasPage, GTMMaterialsPage, PricingArchitecturePage, ROICalculatorsPage, SalesReadinessPage } from '@kyber/pages/gtm';

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    pricingModels: vi.fn(async () => ({ items: [{ name: 'Aether Solution Package Pricing Architecture', base_platform_fee_notes: 'Platform access covers tenant access', premium_modules: ['Decision & Outcome Intelligence'], deployment_pricing: ['standard SaaS'], services_pricing: ['onboarding'], value_based_pricing_notes: ['retained revenue'], usage_dimensions: [{ dimension_key: 'events_ingested', label: 'Events ingested', unit: 'event', billable: true, description: 'Events accepted', metering_source: 'ledger', included_in_tiers: ['platform_access'], notes: 'no dollars' }] }] })),
    gtmMaterials: vi.fn(async () => ({ items: [{ material_id: 'master', title: 'Master Aether Platform One-Pager', material_type: 'one_pager', status: 'sales_ready', market: 'enterprise', solution_package_ids: ['revenue_intelligence_graph'], buyer_personas: ['CMO'], content_blocks: ['Safe claims only'] }] })),
    buyerPersonas: vi.fn(async () => ({ items: [{ persona_id: 'cmo', title: 'CMO', market: 'commercial', relevant_solution_packages: ['revenue_intelligence_graph'], pains: ['churn'], desired_outcomes: ['retention'], objections: ['proof'], proof_needed: ['ROI assumptions'], recommended_collateral: ['master'], pricing_sensitivity: 'value sensitive' }] })),
    roiCalculators: vi.fn(async () => ({ items: [{ calculator_id: 'revenue_intelligence_roi', solution_package_id: 'revenue_intelligence_graph', status: 'internal_ready', inputs: ['monthly revenue'], formulas: ['estimate'], outputs: ['retained revenue estimate'], assumptions: ['buyer baselines'], disclaimer: 'not a guarantee' }] })),
    salesReadiness: vi.fn(async () => ({ ready_to_sell_count: 1, items: [{ package_id: 'revenue_intelligence_graph', package_name: 'Revenue Intelligence Graph', readiness_status: 'sales_ready', ready_to_sell: true, material_count: 2, persona_count: 3, roi_calculator_count: 1, missing_collateral: false, missing_roi_calculator: false, missing_audit_export_support: false, missing_deployment_readiness: false, recommended_next_sales_actions: ['Use approved collateral'] }] })),
  } } },
}));

describe('Kyber GTM pages', () => {
  it('renders Pricing Architecture page', async () => { render(<MemoryRouter><PricingArchitecturePage /></MemoryRouter>); await waitFor(() => expect(screen.getByText('Events ingested')).toBeInTheDocument()); });
  it('renders GTM Materials page', async () => { render(<MemoryRouter><GTMMaterialsPage /></MemoryRouter>); await waitFor(() => expect(screen.getByText('Master Aether Platform One-Pager')).toBeInTheDocument()); });
  it('renders Buyer Persona page', async () => { render(<MemoryRouter><BuyerPersonasPage /></MemoryRouter>); await waitFor(() => expect(screen.getByText('CMO')).toBeInTheDocument()); });
  it('renders ROI Calculator page', async () => { render(<MemoryRouter><ROICalculatorsPage /></MemoryRouter>); await waitFor(() => expect(screen.getByText('revenue_intelligence_roi')).toBeInTheDocument()); });
  it('renders Sales Readiness Dashboard', async () => { render(<MemoryRouter><SalesReadinessPage /></MemoryRouter>); await waitFor(() => expect(screen.getByText('Revenue Intelligence Graph')).toBeInTheDocument()); });
});
