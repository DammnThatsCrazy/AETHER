import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ApplicabilityReport, ExplorationTruth } from '@aether/shared/exploration-contract';
import { TruthBanner } from './truth-banner';

describe('TruthBanner honest states', () => {
  it('renders a not-enabled empty state when the surface is flagged off', () => {
    const html = renderToStaticMarkup(<TruthBanner status="not_enabled" surfaceLabel="Graph" />);
    expect(html).toContain('not enabled');
  });

  it('renders an error state carrying the message', () => {
    const html = renderToStaticMarkup(<TruthBanner status="error" error="boom" />);
    expect(html).toContain('boom');
  });

  it('renders the truth badge, suppression count, and completeness caveat when ready', () => {
    const truth: ExplorationTruth = {
      overall_state: 'partial',
      dimensions: [],
      freshness_watermark: '2026-07-01T00:00:00Z',
    };
    const applicability: ApplicabilityReport = {
      entries: [{ field: 'geography.city', disposition: 'suppressed', reason: 'cohort' }],
    };
    const html = renderToStaticMarkup(
      <TruthBanner
        status="ready"
        truth={truth}
        applicability={applicability}
        completeness={{ complete: false, sampled: true, truncated: false }}
      />,
    );
    expect(html).toContain('Partial');
    expect(html).toContain('1 suppressed');
    expect(html).toContain('Sampled');
  });

  it('is visually distinct across not_enabled / error / ready', () => {
    const a = renderToStaticMarkup(<TruthBanner status="not_enabled" />);
    const b = renderToStaticMarkup(<TruthBanner status="error" error="x" />);
    const c = renderToStaticMarkup(
      <TruthBanner status="ready" truth={{ overall_state: 'ready', dimensions: [] }} />,
    );
    expect(new Set([a, b, c]).size).toBe(3);
  });

  it('discloses readiness, observation class, and the complete measurement truth', () => {
    const html = renderToStaticMarkup(
      <TruthBanner
        status="ready"
        readinessState="credential_waiting"
        observationClass="probabilistic"
        measurement={{
          value_state: 'partial',
          context: 'Campaign incrementality',
          unit: 'USD',
          confidence: 0.72,
          uncertainty: 'wide interval',
          evidence_basis: ['attribution ledger'],
          freshness: { watermark: '2026-07-01T00:00:00Z' },
          restatement: { restated: false },
          attribution_vs_causal: 'attribution',
          materiality_basis: '5% revenue threshold',
        }}
      />,
    );

    expect(html).toContain('data-capability-state="credential_waiting"');
    expect(html).toContain('data-observation-class="probabilistic"');
    expect(html).toContain('Campaign incrementality');
    expect(html).toContain('attribution ledger');
    expect(html).toContain('Attribution result');
    expect(html).toContain('5% revenue threshold');
  });
});
