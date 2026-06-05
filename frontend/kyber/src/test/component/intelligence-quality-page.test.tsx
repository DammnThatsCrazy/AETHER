import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { IntelligenceQualityPage } from '@kyber/pages/intelligence-quality';

const overview = {
  score: { overall_intelligence_quality_score: 0.92, status: 'healthy', scope: 'platform' },
  dimensions: {
    event_quality_score: { score: 0.96, status: 'healthy' },
    graph_quality_score: { score: 0.94, status: 'healthy' },
  },
  open_drift_event_count: 2,
  drift_by_severity: { medium: 1, low: 1 },
};

function mockApi() {
  return {
    api: { admin: { kyber: {
      intelligenceQualityOverview: vi.fn(async () => overview),
      intelligenceQualityTenants: vi.fn(async () => ({ items: [{ tenant_id: 'tenant_alpha', overall_intelligence_quality_score: 0.91, status: 'healthy' }] })),
      intelligenceQualityDriftEvents: vi.fn(async () => ({ items: [{ drift_event_id: 'drift_seed_reco_quality', drift_type: 'recommendation_quality_drift', severity: 'medium', reason: 'low confidence rose', status: 'open' }] })),
      intelligenceQualitySchemaDrift: vi.fn(async () => ({ report: {}, drift_events: [] })),
      intelligenceQualityIdentity: vi.fn(async () => ({ unresolved_entity_rate: 0.038, status: 'healthy' })),
      intelligenceQualityGraph: vi.fn(async () => ({ orphaned_vertices: 73, status: 'healthy' })),
      intelligenceQualityRecommendations: vi.fn(async () => ({ success_rate: 0.71, status: 'healthy' })),
      intelligenceQualityOutcomes: vi.fn(async () => ({ outcome_volume: 1380, status: 'healthy' })),
      intelligenceQualityPlaybooks: vi.fn(async () => ({ run_count: 640, status: 'healthy' })),
      intelligenceQualityContamination: vi.fn(async () => ({ report: { contamination_score: 0.99, status: 'healthy', cross_tenant_identifiers: 0 }, drift_events: [] })),
    } } },
  };
}

vi.mock('@kyber/lib/api', () => mockApi());

describe('Kyber Intelligence Quality page', () => {
  it('renders overview, tenants, drift, and contamination views', async () => {
    render(<MemoryRouter><IntelligenceQualityPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Intelligence Quality')).toBeInTheDocument());
    expect(screen.getByText('Overall quality')).toBeInTheDocument();
    expect(screen.getByText('Open drift events')).toBeInTheDocument();
    expect(screen.getByText('Tenants')).toBeInTheDocument();
    expect(screen.getByText('Drift Events')).toBeInTheDocument();
    expect(screen.getByText('Contamination')).toBeInTheDocument();
  });
});
