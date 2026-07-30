import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  capabilityStates,
  capabilityStateStyle,
  worstCapabilityState,
  isCapabilityState,
  resolveCapabilityState,
  fromImplementationStatus,
  fromDimensionState,
  CapabilityStateBadge,
  CapabilityStatePanel,
  type CapabilityState,
} from './index';

const ALL = capabilityStates as readonly CapabilityState[];

describe('capability state matrix', () => {
  it('defines the complete compatibility and canonical readiness tokens', () => {
    expect(new Set(ALL).size).toBe(ALL.length);
    for (const token of [
      'disabled',
      'disabled_intentionally',
      'not_in_release',
      'unavailable',
      'externally_blocked',
      'not_entitled',
      'not_configured',
      'credential_required',
      'credential_invalid',
      'connection_testing',
      'credential_waiting',
      'provisioning',
      'replay_validated',
      'sandbox_validated',
      'partner_live',
      'live',
      'degraded',
      'stale',
      'partial',
      'error',
      'kill_switch_active',
    ]) {
      expect(isCapabilityState(token)).toBe(true);
    }
  });

  it('gives every state a distinct label + glyph', () => {
    const labels = ALL.map((s) => capabilityStateStyle(s).label);
    const glyphs = ALL.map((s) => capabilityStateStyle(s).glyph);
    expect(new Set(labels).size).toBe(ALL.length);
    expect(new Set(glyphs).size).toBe(ALL.length);
  });

  it('marks only canonical live and compatibility partner_live as fully live', () => {
    expect(capabilityStateStyle('partner_live').notLive).toBe(false);
    expect(capabilityStateStyle('partner_live').tone).toBe('live');
    expect(capabilityStateStyle('live').notLive).toBe(false);
    expect(capabilityStateStyle('live').tone).toBe('live');
    for (const s of ALL) {
      if (s === 'partner_live' || s === 'live') continue;
      expect(capabilityStateStyle(s).tone).not.toBe('live');
    }
    // Credential/validation-ladder states must never claim to be live.
    for (const s of ['not_configured', 'credential_required', 'credential_invalid', 'connection_testing', 'credential_waiting', 'replay_validated', 'sandbox_validated', 'kill_switch_active'] as CapabilityState[]) {
      expect(capabilityStateStyle(s).notLive).toBe(true);
    }
  });
});

describe('CapabilityStateBadge', () => {
  it('renders a visually distinct treatment for every state', () => {
    const rendered = ALL.map((s) => renderToStaticMarkup(<CapabilityStateBadge state={s} />));
    // Distinctness: no two states produce identical markup.
    expect(new Set(rendered).size).toBe(ALL.length);
    // Each carries its machine-readable marker + human label.
    ALL.forEach((s, i) => {
      const html = rendered[i]!;
      expect(html).toContain(`data-capability-state="${s}"`);
      expect(html).toContain(capabilityStateStyle(s).label);
    });
  });

  it('exposes a tone marker and defaults the tooltip to the description', () => {
    const html = renderToStaticMarkup(<CapabilityStateBadge state="credential_waiting" />);
    expect(html).toContain('data-capability-tone="progress"');
    expect(html).toContain(capabilityStateStyle('credential_waiting').description);
  });

  it('accepts a label + reason override', () => {
    const html = renderToStaticMarkup(
      <CapabilityStateBadge state="partner_live" label="Stripe · live" reason="last event 2m ago" />,
    );
    expect(html).toContain('Stripe · live');
    expect(html).toContain('title="last event 2m ago"');
  });
});

describe('CapabilityStatePanel', () => {
  it('distinguishes disabled / not_entitled / not_configured instead of one generic empty state', () => {
    const disabled = renderToStaticMarkup(<CapabilityStatePanel state="disabled" />);
    const notEntitled = renderToStaticMarkup(<CapabilityStatePanel state="not_entitled" />);
    const notConfigured = renderToStaticMarkup(<CapabilityStatePanel state="not_configured" />);
    expect(new Set([disabled, notEntitled, notConfigured]).size).toBe(3);
    expect(disabled).toContain('data-capability-state="disabled"');
    expect(notEntitled).toContain('Not entitled');
    expect(notConfigured).toContain('Not configured');
  });
});

describe('server-status mappings (never faked)', () => {
  it('maps ImplementationStatus onto the matrix', () => {
    expect(fromImplementationStatus('provider_live')).toBe('partner_live');
    expect(fromImplementationStatus('credential_gated')).toBe('credential_required');
    expect(fromImplementationStatus('staging_validation_required')).toBe('sandbox_validated');
    expect(fromImplementationStatus('disabled_compliance_review')).toBe('disabled');
    expect(fromImplementationStatus('mocked_local')).toBe('not_configured');
  });

  it('maps DimensionState onto the matrix', () => {
    expect(fromDimensionState('ready')).toBe('partner_live');
    expect(fromDimensionState('degraded')).toBe('degraded');
    expect(fromDimensionState('stale')).toBe('stale');
    expect(fromDimensionState('partial')).toBe('partial');
    expect(fromDimensionState('error')).toBe('error');
    expect(fromDimensionState('suppressed')).toBe('not_entitled');
  });

  it('normalizes ad-hoc server status strings, and returns null for the unknown', () => {
    expect(resolveCapabilityState('configured')).toBe('partner_live');
    expect(resolveCapabilityState('healthy')).toBe('partner_live');
    expect(resolveCapabilityState('not_configured')).toBe('not_configured');
    expect(resolveCapabilityState('pending_verification')).toBe('connection_testing');
    expect(resolveCapabilityState('degraded')).toBe('degraded');
    expect(resolveCapabilityState('kill switch')).toBe('kill_switch_active');
    expect(resolveCapabilityState('partner_live')).toBe('partner_live');
    expect(resolveCapabilityState('')).toBeNull();
    expect(resolveCapabilityState(undefined)).toBeNull();
    expect(resolveCapabilityState('wat-is-this')).toBeNull();
  });
});

describe('worstCapabilityState', () => {
  it('never lets an overall roll-up look better than its weakest state', () => {
    expect(worstCapabilityState(['partner_live', 'partner_live'])).toBe('partner_live');
    expect(worstCapabilityState(['partner_live', 'stale'])).toBe('stale');
    expect(worstCapabilityState(['partner_live', 'degraded', 'stale'])).toBe('degraded');
    expect(worstCapabilityState(['partner_live', 'kill_switch_active', 'error'])).toBe('kill_switch_active');
    expect(worstCapabilityState([])).toBe('unavailable');
  });
});
