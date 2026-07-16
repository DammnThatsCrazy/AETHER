import { describe, expect, it } from 'vitest';
import {
  isTerminalImportStatus,
  primitiveFields,
} from './imports';

describe('tenant import contract helpers', () => {
  it('distinguishes terminal and active import states', () => {
    expect(isTerminalImportStatus('committed')).toBe(true);
    expect(isTerminalImportStatus('rolled_back')).toBe(true);
    expect(isTerminalImportStatus('validating')).toBe(false);
  });

  it('returns canonical primitive fields', () => {
    expect(primitiveFields('metric')).toEqual([
      'metric_name',
      'entity_ref',
      'value',
      'unit',
      'observed_at',
    ]);
  });
});
