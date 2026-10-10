import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DataQualityPage } from '@aether-app/pages/data-quality';

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { dataQuality: {
    overview: vi.fn(async () => ({
      score: { overall_intelligence_quality_score: 0.93, status: 'healthy' },
      dimensions: {
        event_quality_score: { score: 0.96, status: 'healthy' },
        graph_quality_score: { score: 0.94, status: 'healthy' },
      },
      open_drift_event_count: 0,
    })),
    events: vi.fn(async () => ({ event_volume: 1000000, schema_validation_failure_rate: 0.004, duplicate_event_count: 210, status: 'healthy' })),
    recommendations: vi.fn(async () => ({ success_rate: 0.71, low_confidence_recommendation_rate: 0.11, status: 'healthy' })),
    graph: vi.fn(async () => ({ orphaned_vertices: 73, dangling_edges: 12, status: 'healthy' })),
  } },
}));

describe('Aether Data Quality page', () => {
  it('renders overall quality, dimensions, and metric cards', async () => {
    render(<DataQualityPage />);
    await waitFor(() => expect(screen.getByText('Data Quality')).toBeInTheDocument());
    expect(screen.getByText('Overall intelligence quality')).toBeInTheDocument();
    expect(screen.getByText('Quality by dimension')).toBeInTheDocument();
    expect(screen.getByText('Event quality detail')).toBeInTheDocument();
    expect(screen.getByText('Recommendation quality detail')).toBeInTheDocument();
    expect(screen.getByText('Graph quality detail')).toBeInTheDocument();
  });
});
