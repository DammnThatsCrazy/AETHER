import { describe, expect, it } from 'vitest';

import { formatCount, formatCurrency, formatDecimal } from './number';

const EN = { locale: 'en-US' };
const DE = { locale: 'de-DE' };

describe('formatCount', () => {
  it('groups thousands in the explicit locale', () => {
    expect(formatCount(1234567, EN)).toBe('1,234,567');
    expect(formatCount(1234567, DE)).toBe('1.234.567');
  });

  it('matches the legacy bare toLocaleString() default behavior', () => {
    expect(formatCount(0, EN)).toBe('0');
    expect(formatCount(1234.5678, EN)).toBe((1234.5678).toLocaleString('en-US'));
  });
});

describe('formatDecimal', () => {
  it('honors maximumFractionDigits', () => {
    expect(formatDecimal(1234.5678, EN, { maximumFractionDigits: 0 })).toBe('1,235');
    expect(formatDecimal(1234.5678, EN, { maximumFractionDigits: 2 })).toBe('1,234.57');
  });

  it('honors minimumFractionDigits', () => {
    expect(
      formatDecimal(5, EN, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    ).toBe('5.00');
  });
});

describe('formatCurrency', () => {
  it('renders explicit currency codes', () => {
    expect(formatCurrency(12.5, 'usd', EN)).toBe('$12.50');
    expect(formatCurrency(12.5, 'EUR', EN)).toBe('€12.50');
  });
});
