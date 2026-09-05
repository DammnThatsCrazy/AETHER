import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ReportingValueDisplay, buildReportingValueRender } from './reporting-value-display';
import type { DisplayCurrencyQuote, ReportingValuationLike } from './reporting-value';

// Component tests render with react-dom/server and resolve canonical asset
// metadata through @aether/shared/financial-assets — they run in the full CI
// install (react + @aether/shared present).

function markup(
  value: ReportingValuationLike | null | undefined,
  displayCurrency?: DisplayCurrencyQuote | null | undefined,
): string {
  return renderToStaticMarkup(
    <ReportingValueDisplay value={value} displayCurrency={displayCurrency} />,
  );
}

describe('ReportingValueDisplay', () => {
  const eurValue: ReportingValuationLike = {
    reporting_asset_id: 'fiat:EUR',
    reporting_amount: '1049.5',
  };

  it('renders the canonical reporting figure when present', () => {
    const html = markup(eurValue);
    expect(html).toContain('€1,049.50');
    expect(html).toContain('EUR');
  });

  it('renders an explicit unavailable state (never a zero) when reporting_amount is null', () => {
    const html = markup({ reporting_asset_id: 'fiat:EUR', reporting_amount: null });
    expect(html).toContain('Reporting unavailable');
    expect(html).not.toContain('$0.00');
    expect(html).not.toContain('>0<');
  });

  it('shows the reporting figure plus an explicit note when a display currency lacks a rate', () => {
    const html = markup(eurValue, { currencyId: 'fiat:USD' });
    expect(html).toContain('€1,049.50');
    expect(html).toContain('Display conversion unavailable');
  });

  it('shows the converted figure when an explicit rate is supplied', () => {
    const html = markup(eurValue, { currencyId: 'fiat:USD', rate: '1.2137' });
    expect(html).toContain('$1,273.77');
    expect(html).toContain('USD');
    expect(html).toContain('Reporting: €1,049.50 EUR');
  });
});

describe('buildReportingValueRender (headless)', () => {
  function deepFreeze<T>(value: T): T {
    if (value !== null && typeof value === 'object') {
      for (const key of Object.keys(value as object)) {
        deepFreeze((value as Record<string, unknown>)[key]);
      }
      Object.freeze(value);
    }
    return value;
  }

  it('never mutates a deep-frozen value object', () => {
    const value = deepFreeze<ReportingValuationLike>({
      reporting_asset_id: 'fiat:EUR',
      reporting_amount: '1049.5',
    });
    const quote = deepFreeze<DisplayCurrencyQuote>({ currencyId: 'fiat:USD', rate: '1.2137' });
    const render = buildReportingValueRender(value, quote);
    expect(render.kind).toBe('reporting-display-converted');
    expect(value.reporting_amount).toBe('1049.5');
    expect(value.reporting_asset_id).toBe('fiat:EUR');
  });

  it('rejects a bare reporting symbol without guessing', () => {
    const render = buildReportingValueRender({ reporting_asset_id: 'USD', reporting_amount: '5' });
    expect(render.kind).toBe('unavailable-reporting');
    expect(render.unavailableReason).toBe('unrecognized-reporting-asset');
  });
});
