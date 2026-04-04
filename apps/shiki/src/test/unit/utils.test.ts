import { describe, it, expect } from 'vitest';
import { formatCompactNumber, formatPercentage, formatDuration, truncate, formatRelativeTime, formatTimestamp } from '@shiki/lib/utils';

describe('formatCompactNumber', () => {
  it('formats millions', () => {
    expect(formatCompactNumber(1_500_000)).toBe('1.5M');
  });
  it('formats thousands', () => {
    expect(formatCompactNumber(42_300)).toBe('42.3K');
  });
  it('formats small numbers as-is', () => {
    expect(formatCompactNumber(500)).toBe('500');
  });
});

describe('formatPercentage', () => {
  it('converts decimal to percentage', () => {
    expect(formatPercentage(0.856)).toBe('85.6%');
  });
  it('respects decimal places', () => {
    expect(formatPercentage(0.5, 0)).toBe('50%');
  });
});

describe('formatDuration', () => {
  it('formats milliseconds', () => {
    expect(formatDuration(450)).toBe('450ms');
  });
  it('formats seconds', () => {
    expect(formatDuration(5400)).toBe('5.4s');
  });
  it('formats minutes and seconds', () => {
    expect(formatDuration(125000)).toBe('2m 5s');
  });
  it('formats hours and minutes', () => {
    expect(formatDuration(7_260_000)).toBe('2h 1m');
  });
});

describe('truncate', () => {
  it('returns short strings unchanged', () => {
    expect(truncate('hello', 10)).toBe('hello');
  });
  it('truncates long strings with ellipsis', () => {
    expect(truncate('hello world', 8)).toBe('hello w\u2026');
  });
});

describe('formatTimestamp', () => {
  it('formats ISO string', () => {
    const result = formatTimestamp('2024-06-15T14:30:00.000Z');
    expect(result).toContain('2024');
    expect(result).toContain('14');
  });
});

describe('formatRelativeTime', () => {
  it('returns relative time string', () => {
    const recent = new Date(Date.now() - 5 * 60_000).toISOString();
    const result = formatRelativeTime(recent);
    expect(result).toContain('minute');
  });
});
