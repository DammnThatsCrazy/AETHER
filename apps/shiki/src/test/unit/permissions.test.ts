import { describe, it, expect } from 'vitest';
import { canPerformAction, getMaxActionClass } from '@shiki/features/permissions';
import type { ShikiRole, ActionClass } from '@shiki/types';

describe('getMaxActionClass', () => {
  it('returns 4 for executive operator', () => {
    expect(getMaxActionClass('shiki_executive_operator')).toBe(4);
  });
  it('returns 5 for engineering command', () => {
    expect(getMaxActionClass('shiki_engineering_command')).toBe(5);
  });
  it('returns 2 for specialist operator', () => {
    expect(getMaxActionClass('shiki_specialist_operator')).toBe(2);
  });
  it('returns 0 for observer', () => {
    expect(getMaxActionClass('shiki_observer')).toBe(0);
  });
});

describe('canPerformAction', () => {
  it('allows read-only for all roles', () => {
    const roles: ShikiRole[] = [
      'shiki_executive_operator',
      'shiki_engineering_command',
      'shiki_specialist_operator',
      'shiki_observer',
    ];
    for (const role of roles) {
      const result = canPerformAction(role, 0);
      expect(result.allowed).toBe(true);
      expect(result.requiresApproval).toBe(false);
    }
  });

  it('denies class 1 for observer', () => {
    const result = canPerformAction('shiki_observer', 1);
    expect(result.allowed).toBe(false);
  });

  it('denies class 5 for executive operator', () => {
    const result = canPerformAction('shiki_executive_operator', 5);
    expect(result.allowed).toBe(false);
  });

  it('allows class 5 for engineering command', () => {
    const result = canPerformAction('shiki_engineering_command', 5);
    expect(result.allowed).toBe(true);
  });

  it('denies class 3 for specialist operator', () => {
    const result = canPerformAction('shiki_specialist_operator', 3);
    expect(result.allowed).toBe(false);
  });
});
