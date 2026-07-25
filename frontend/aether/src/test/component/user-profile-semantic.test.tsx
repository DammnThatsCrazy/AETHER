import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeAll, afterEach, afterAll } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

import { SemanticSentimentSection } from '@aether-app/pages/user-profile/user-profile-page';

// Requests use relative paths (/v1/...) which resolve against the jsdom origin.
const API = 'http://localhost:8000';

function envelope(data: unknown) {
  return { data, status: 'ok', timestamp: new Date().toISOString() };
}

function semanticState(overrides: Record<string, unknown> = {}) {
  return {
    state_id: 'ess_populated_001',
    tenant_id: 'tenant_demo_001',
    entity_ref: 'user-sem-populated',
    entity_type: 'profile',
    subject_ref: 'user-sem-populated',
    window_start: '2026-07-01T00:00:00Z',
    window_end: '2026-07-23T00:00:00Z',
    active_topics: ['pricing', 'onboarding'],
    dominant_narratives: ['value_for_money'],
    stance_distribution: { supportive: 0.6, opposed: 0.25, neutral: 0.15 },
    intent_distribution: { evaluate: 0.7, purchase: 0.3 },
    semantic_summary: 'Predominantly supportive about pricing with rising onboarding interest.',
    semantic_baseline: {},
    semantic_delta: {},
    persistence: 'medium_ttl',
    volatility: 0.2,
    observation_count: 14,
    unique_source_count: 3,
    model_mix: { 'deterministic-semantic-classifier': 14 },
    confidence: 0.82,
    freshness: 'fresh',
    evidence_refs: [
      {
        evidence_id: 'ev_sem_001',
        source_type: 'event',
        source_ref: 'evt_abc',
        observed_at: '2026-07-22T12:00:00Z',
        confidence: 0.9,
      },
    ],
    version: 1,
    computed_at: new Date().toISOString(),
    ...overrides,
  };
}

const server = setupServer(
  http.get(`${API}/v1/profile/user-sem-populated/semantic`, () =>
    HttpResponse.json(envelope({
      user_id: 'user-sem-populated',
      semantic: semanticState(),
      computed: true,
      provenance: { sources: ['semantic_gold_state'] },
    })),
  ),
  http.get(`${API}/v1/profile/user-sem-empty/semantic`, () =>
    HttpResponse.json(envelope({
      user_id: 'user-sem-empty',
      semantic: semanticState({
        state_id: 'ess_empty_001',
        entity_ref: 'user-sem-empty',
        subject_ref: 'user-sem-empty',
        active_topics: [],
        dominant_narratives: [],
        stance_distribution: {},
        intent_distribution: {},
        semantic_summary: 'insufficient_data',
        observation_count: 0,
        unique_source_count: 0,
        model_mix: {},
        confidence: 0,
        freshness: 'unknown',
        evidence_refs: [],
      }),
      computed: false,
      provenance: { sources: ['semantic_gold_state'] },
    })),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe('Profile360 — Semantic sentiment section', () => {
  it('renders summary, topic chips, stance distribution, confidence and freshness', async () => {
    render(<SemanticSentimentSection userId="user-sem-populated" />);

    await waitFor(() =>
      expect(
        screen.getByText('Predominantly supportive about pricing with rising onboarding interest.'),
      ).toBeInTheDocument(),
    );

    // Section title
    expect(screen.getByText('Semantic sentiment')).toBeInTheDocument();

    // Active topics as chips
    expect(screen.getByText('pricing')).toBeInTheDocument();
    expect(screen.getByText('onboarding')).toBeInTheDocument();

    // Stance distribution rows with weights
    expect(screen.getByText('supportive')).toBeInTheDocument();
    expect(screen.getByText('opposed')).toBeInTheDocument();
    expect(screen.getByText('neutral')).toBeInTheDocument();
    expect(screen.getByText('60%')).toBeInTheDocument();
    expect(screen.getByText('25%')).toBeInTheDocument();

    // Confidence + observation provenance
    expect(screen.getByText('Confidence 82%')).toBeInTheDocument();
    expect(screen.getByText('14 observations · 3 sources')).toBeInTheDocument();

    // FreshnessIndicator renders "<state> as of <time>"
    expect(screen.getByText(/as of/)).toBeInTheDocument();
  });

  it('renders an honest empty state on insufficient data — no fabricated numbers', async () => {
    render(<SemanticSentimentSection userId="user-sem-empty" />);

    await waitFor(() =>
      expect(screen.getByText('No semantic signal yet')).toBeInTheDocument(),
    );

    expect(
      screen.getByText(/Not enough semantic observations have been ingested/),
    ).toBeInTheDocument();

    // No fake confidence / stance / freshness rendered
    expect(screen.queryByText(/Confidence/)).not.toBeInTheDocument();
    expect(screen.queryByText('insufficient_data')).not.toBeInTheDocument();
    expect(screen.queryByText(/as of/)).not.toBeInTheDocument();
  });
});
