import { render, screen, within } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { TouchpointEvidenceInspector } from '@aether-app/features/journey';

// jsdom does not implement the native <dialog> modal methods the shared Modal
// calls in an effect; stub them so the component mounts. Content still renders
// because the Modal renders `open && children` unconditionally.
beforeAll(() => {
  if (!HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = vi.fn();
  }
  if (!HTMLDialogElement.prototype.close) {
    HTMLDialogElement.prototype.close = vi.fn();
  }
});

const DIRECT_TOUCHPOINT = {
  step_id: 'tp_direct',
  source_class: 'direct_unknown',
  source: '(direct)',
  medium: '(none)',
  proof_level: 'none',
  classification_confidence: 0.42,
  classifier_version: 'source-classifier@3.1.0',
  classification_rule: 'no_referral_evidence',
  evidence_conflicts: ['channel_ambiguous', 'utm_missing'],
  campaign_id: null,
  campaign_resolution_status: 'unresolved',
  journey_role: 'first_touch',
  platform: 'ios',
  sdk: 'aether-swift',
  sanitization_status: 'sanitized',
  actor_type: 'human',
};

const PAID_TOUCHPOINT = {
  step_id: 'tp_paid',
  source_class: 'paid_search',
  source: 'google',
  proof_level: 'declared',
  evidence_signals: [{ signal: 'gclid_present' }, 'utm_declaration'],
  actor_type: 'machine',
};

describe('TouchpointEvidenceInspector', () => {
  it('renders the canonical Direct / Unknown label, proof, conflicts and first-touch position', () => {
    render(
      <TouchpointEvidenceInspector
        touchpoint={DIRECT_TOUCHPOINT}
        open
        onClose={() => {}}
        isFirstTouch
        isLatestTouch={false}
      />,
    );

    // Canonical registry label — never a typed-URL claim.
    expect(screen.getAllByText('Direct / Unknown').length).toBeGreaterThan(0);
    expect(screen.queryByText('Typed URL')).toBeNull();

    // Proof level + confidence.
    expect(screen.getByText('Proof level')).toBeInTheDocument();
    expect(screen.getByText('42%')).toBeInTheDocument();

    // Evidence conflicts are surfaced.
    expect(screen.getByText('channel_ambiguous')).toBeInTheDocument();
    expect(screen.getByText('utm_missing')).toBeInTheDocument();

    // Winning rule + classifier version.
    expect(screen.getByText('no_referral_evidence')).toBeInTheDocument();
    expect(screen.getByText('source-classifier@3.1.0')).toBeInTheDocument();

    // Campaign resolution status + first-touch position.
    expect(screen.getByText('unresolved')).toBeInTheDocument();
    expect(screen.getByText('First touch')).toBeInTheDocument();

    // Human-eligible (actor_type human, no machine signal).
    expect(screen.getByText('Human-eligible')).toBeInTheDocument();
  });

  it('normalizes legacy "direct" to Direct / Unknown from the registry', () => {
    render(
      <TouchpointEvidenceInspector
        touchpoint={{ step_id: 'tp_legacy', source_class: 'direct' }}
        open
        onClose={() => {}}
      />,
    );
    expect(screen.getAllByText('Direct / Unknown').length).toBeGreaterThan(0);
    expect(screen.queryByText('Typed URL')).toBeNull();
  });

  it('renders paid-search evidence signals and flags machine traffic', () => {
    render(
      <TouchpointEvidenceInspector
        touchpoint={PAID_TOUCHPOINT}
        open
        onClose={() => {}}
        isLatestTouch
      />,
    );
    // Canonical paid-search label from the registry (not hardcoded).
    expect(screen.getAllByText('Paid Search').length).toBeGreaterThan(0);
    // Evidence signals rendered from object + string shapes.
    expect(screen.getByText('gclid_present')).toBeInTheDocument();
    expect(screen.getByText('utm_declaration')).toBeInTheDocument();
    // Machine actor → machine-excluded.
    expect(screen.getByText('Machine-excluded')).toBeInTheDocument();
    expect(screen.getByText('Latest touch')).toBeInTheDocument();
  });

  it('renders defensively when optional fields are absent (no invented data)', () => {
    render(
      <TouchpointEvidenceInspector
        touchpoint={{ step_id: 'tp_sparse', source_class: 'organic_search' }}
        open
        onClose={() => {}}
      />,
    );
    expect(screen.getAllByText('Organic Search').length).toBeGreaterThan(0);
    // Missing conflicts / signals render honest empty copy, not fabricated rows.
    expect(screen.getByText('None')).toBeInTheDocument();
    expect(screen.getByText('None reported')).toBeInTheDocument();
    // Mid-journey when neither first nor latest.
    expect(screen.getByText('Mid-journey')).toBeInTheDocument();
  });

  it('renders nothing when there is no touchpoint', () => {
    const { container } = render(
      <TouchpointEvidenceInspector touchpoint={null} open onClose={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
