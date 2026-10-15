/**
 * Pure permission arithmetic.
 *
 * Note what these tests can no longer do: there is no role argument any more.
 * The ceiling is a number the backend sent (`max_action_class` /
 * `max_disclosure`), so the only thing left to test on the client is the
 * comparison — which is exactly the point.
 */

import { describe, it, expect } from 'vitest';
import {
  checkActionClass,
  checkDisclosureLevel,
  hasAllCapabilities,
  hasAnyCapability,
  hasCapability,
  LEGACY_GATE_CAPABILITIES,
  LEGACY_GATE_NAMES,
} from '@kyber/features/permissions';
import type { ActionClass } from '@kyber/types';

describe('checkActionClass', () => {
  it('allows read-only class 0 at every ceiling', () => {
    for (const ceiling of [0, 1, 2, 3, 4, 5]) {
      const result = checkActionClass(ceiling, 0);
      expect(result.allowed).toBe(true);
      expect(result.requiresApproval).toBe(false);
    }
  });

  it('refuses anything above the backend ceiling', () => {
    const classes: ActionClass[] = [1, 2, 3, 4, 5];
    for (const actionClass of classes) {
      expect(checkActionClass(0, actionClass).allowed).toBe(false);
    }
    expect(checkActionClass(2, 3).allowed).toBe(false);
    expect(checkActionClass(4, 5).allowed).toBe(false);
  });

  it('allows exactly at the ceiling', () => {
    expect(checkActionClass(5, 5).allowed).toBe(true);
    expect(checkActionClass(2, 2).allowed).toBe(true);
  });

  it('explains a refusal in terms of the backend ceiling', () => {
    expect(checkActionClass(1, 4).reason).toContain('backend ceiling of 1');
  });
});

describe('checkDisclosureLevel', () => {
  it('refuses above the ceiling and allows at or below it', () => {
    expect(checkDisclosureLevel(0, 1).allowed).toBe(false);
    expect(checkDisclosureLevel(3, 3).allowed).toBe(true);
    expect(checkDisclosureLevel(3, 2).allowed).toBe(true);
    expect(checkDisclosureLevel(3, 5).allowed).toBe(false);
  });
});

describe('capability predicates', () => {
  const granted = ['kyber.tenant.mirror.read', 'kyber.approvals.decide'];

  it('matches only exact capability ids', () => {
    expect(hasCapability(granted, 'kyber.approvals.decide')).toBe(true);
    expect(hasCapability(granted, 'kyber.approvals')).toBe(false);
    expect(hasCapability([], 'kyber.approvals.decide')).toBe(false);
  });

  it('supports any/all semantics', () => {
    expect(hasAnyCapability(granted, ['kyber.nope', 'kyber.approvals.decide'])).toBe(true);
    expect(hasAnyCapability(granted, ['kyber.nope'])).toBe(false);
    expect(hasAllCapabilities(granted, granted)).toBe(true);
    expect(hasAllCapabilities(granted, [...granted, 'kyber.nope'])).toBe(false);
  });
});

describe('legacy gate aliases', () => {
  it('maps every legacy name to a namespaced capability id', () => {
    for (const gate of LEGACY_GATE_NAMES) {
      expect(LEGACY_GATE_CAPABILITIES[gate]).toMatch(/^kyber\./);
    }
  });

  it('no longer exposes canViewAll', () => {
    expect(LEGACY_GATE_NAMES as readonly string[]).not.toContain('canViewAll');
  });
});
