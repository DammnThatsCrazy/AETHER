import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeAll, afterEach, afterAll } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

import { SemanticOverlayPanel } from '@aether-app/pages/journey-explorer/journey-explorer-page';

const API = 'http://localhost:8000';

function envelope(data: unknown) {
  return { data, status: 'ok', timestamp: new Date().toISOString() };
}

function overlayResponse(subjectRef: string) {
  if (subjectRef === 'profile-sem-empty') {
    return envelope({
      overlay_type: 'semantic_sentiment',
      node_overlays: [],
      edge_overlays: [],
      partial: false,
      causal_confidence: 'observed_sequence',
    });
  }
  return envelope({
    overlay_type: 'semantic_sentiment',
    node_overlays: [
      {
        entity_ref: 'profile-sem-populated',
        stance: 'strongly_supportive',
        topics: ['pricing', 'loyalty_program'],
        confidence: 0.91,
        valid_from: '2026-07-20T10:00:00Z',
        evidence_refs: [
          {
            evidence_id: 'ev_overlay_001',
            source_type: 'event',
            source_ref: 'evt_checkout_123',
            observed_at: '2026-07-20T10:00:00Z',
            confidence: 0.9,
          },
          {
            evidence_id: 'ev_overlay_002',
            source_type: 'message',
            source_ref: 'msg_support_456',
            observed_at: '2026-07-19T08:30:00Z',
            confidence: 0.7,
          },
        ],
      },
      {
        entity_ref: 'profile-sem-populated',
        stance: 'weakly_opposed',
        topics: ['checkout_friction'],
        confidence: 0.44,
        valid_from: '2026-07-18T09:00:00Z',
        evidence_refs: [],
      },
    ],
    edge_overlays: [],
    partial: false,
    causal_confidence: 'observed_sequence',
  });
}

const server = setupServer(
  http.post(`${API}/v1/graph/semantic-overlay`, async ({ request }) => {
    const body = (await request.json()) as { subject_ref?: string };
    return HttpResponse.json(overlayResponse(body.subject_ref ?? ''));
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe('Journey explorer — semantic overlay panel', () => {
  it('renders stance and topic chips per node overlay', async () => {
    render(<SemanticOverlayPanel profileId="profile-sem-populated" />);

    await waitFor(() =>
      expect(screen.getByText('strongly supportive')).toBeInTheDocument(),
    );

    expect(screen.getByText('Semantic Overlay')).toBeInTheDocument();
    expect(screen.getByText('weakly opposed')).toBeInTheDocument();
    expect(screen.getByText('pricing')).toBeInTheDocument();
    expect(screen.getByText('loyalty_program')).toBeInTheDocument();
    expect(screen.getByText('checkout_friction')).toBeInTheDocument();
    expect(screen.getByText('confidence 91%')).toBeInTheDocument();
    expect(screen.getByText('confidence 44%')).toBeInTheDocument();

    // Entity-level boundary stated (per-step annotation is backend-blocked)
    expect(screen.getByText(/Per-step\s+journey annotation is not yet available/)).toBeInTheDocument();
  });

  it('opens the evidence drawer with evidence refs on click', async () => {
    render(<SemanticOverlayPanel profileId="profile-sem-populated" />);

    await waitFor(() =>
      expect(screen.getByText('strongly supportive')).toBeInTheDocument(),
    );

    // Only the overlay with evidence refs exposes the toggle
    const toggle = screen.getByText('[>] evidence (2)');
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(screen.getByText('ev_overlay_001')).toBeInTheDocument(),
    );
    expect(screen.getByText('ev_overlay_002')).toBeInTheDocument();
    expect(screen.getByText('event · evt_checkout_123')).toBeInTheDocument();
    expect(screen.getByText('message · msg_support_456')).toBeInTheDocument();
    expect(screen.getByText(/Evidence —/)).toBeInTheDocument();

    // Close again
    fireEvent.click(screen.getByText('[x]'));
    expect(screen.queryByText('ev_overlay_001')).not.toBeInTheDocument();
  });

  it('renders an honest empty state when no semantic observations exist', async () => {
    render(<SemanticOverlayPanel profileId="profile-sem-empty" />);

    await waitFor(() =>
      expect(screen.getByText('No semantic observations')).toBeInTheDocument(),
    );

    expect(
      screen.getByText(/No semantic observations have been recorded for this profile yet/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/confidence/)).not.toBeInTheDocument();
  });
});
