import { describe, expect, it } from 'vitest';
import {
  REPORTING_UNAVAILABLE,
  DISPLAY_CONVERSION_UNAVAILABLE,
  isDecimalString,
  convertDecimalAmount,
  formatDecimalAmount,
  decorateAmountText,
  composeReportingDisplay,
  type AssetDisplayMeta,
  type DisplayCurrencyQuote,
  type ReportingValueRender,
  type ReportingValuationLike,
} from './reporting-value';

// ---------------------------------------------------------------------------
// Fixtures (what resolveReportingAssetMeta returns from financial-assets.ts)
// ---------------------------------------------------------------------------

const EUR_META: AssetDisplayMeta = {
  assetId: 'fiat:EUR',
  code: 'EUR',
  symbol: '€',
  minorUnits: 2,
};

const USD_META: AssetDisplayMeta = {
  assetId: 'fiat:USD',
  code: 'USD',
  symbol: '$',
  minorUnits: 2,
};

const JPY_META: AssetDisplayMeta = {
  assetId: 'fiat:JPY',
  code: 'JPY',
  symbol: '¥',
  minorUnits: 0,
};

const ETH_META: AssetDisplayMeta = {
  assetId: 'crypto:ETH',
  code: 'ETH',
  symbol: null,
  minorUnits: null,
};

function renderFor(
  reportingAmount: string | null | undefined,
  reportingAssetId: string | null | undefined,
  assetMeta: AssetDisplayMeta | null | undefined,
  displayCurrency?: DisplayCurrencyQuote | null | undefined,
  displayCurrencyMeta?: AssetDisplayMeta | null | undefined,
): ReportingValueRender {
  return composeReportingDisplay({
    reportingAmount,
    reportingAssetId,
    assetMeta,
    displayCurrencyQuote: displayCurrency ?? null,
    displayCurrencyMeta: displayCurrencyMeta ?? null,
  });
}

describe('reporting value present', () => {
  it('renders the canonical reporting amount with symbol + minor units', () => {
    const render = renderFor('1049.5', 'fiat:EUR', EUR_META);
    expect(render.kind).toBe('reporting');
    expect(render.reportingAmountText).toBe('1,049.50');
    expect(render.reportingText).toBe('€1,049.50');
    expect(render.reportingCode).toBe('EUR');
    expect(render.reportingAssetId).toBe('fiat:EUR');
    expect(render.convertedText).toBeNull();
    expect(render.unavailableReason).toBeNull();
  });

  it('renders a zero-minor-unit asset (JPY) without decimals', () => {
    expect(renderFor('1234', 'fiat:JPY', JPY_META).reportingText).toBe('¥1,234');
  });

  it('renders a no-symbol asset (crypto ticker as code, no guessed glyph)', () => {
    const render = renderFor('1.8432', 'crypto:ETH', ETH_META);
    expect(render.kind).toBe('reporting');
    expect(render.reportingText).toBe('1.8432');
    expect(render.reportingCode).toBe('ETH');
  });

  it('treats a genuine zero as a priced value, not an absence', () => {
    const render = renderFor('0', 'fiat:EUR', EUR_META);
    expect(render.kind).toBe('reporting');
    expect(render.reportingText).toBe('€0.00');
    expect(render.unavailableReason).toBeNull();
  });
});

describe('absent reporting amount is never a monetary zero', () => {
  it.each([null, undefined, ''])('renders "Reporting unavailable" for %p', (amount) => {
    const render = renderFor(amount, 'fiat:EUR', EUR_META);
    expect(render.kind).toBe('unavailable-reporting');
    expect(render.unavailableReason).toBe('no-reporting-amount');
    expect(render.reportingText).toBe(REPORTING_UNAVAILABLE);
    expect(render.reportingText).not.toBe('0');
    expect(render.reportingText).not.toBe('$0.00');
    expect(render.reportingCode).toBeNull();
  });

  it('honors a caller fallback label', () => {
    const render = composeReportingDisplay({
      reportingAmount: null,
      reportingAssetId: 'fiat:EUR',
      assetMeta: EUR_META,
      fallbackLabel: 'No reporting figure',
    });
    expect(render.reportingText).toBe('No reporting figure');
  });

  it('rejects a non-decimal-string amount instead of float-parsing it', () => {
    // A JS number payload is a contract violation — never Number()-formatted.
    const render = renderFor('not-a-decimal', 'fiat:EUR', EUR_META);
    expect(render.kind).toBe('unavailable-reporting');
    expect(render.unavailableReason).toBe('invalid-reporting-amount');
  });
});

describe('bare / non-namespaced reporting asset id', () => {
  it('rejects a bare symbol without guessing symbol or decimals', () => {
    const render = renderFor('1049.5', 'USD', null);
    expect(render.kind).toBe('unavailable-reporting');
    expect(render.unavailableReason).toBe('unrecognized-reporting-asset');
    expect(render.reportingText).toBe(REPORTING_UNAVAILABLE);
    expect(render.reportingCode).toBeNull();
  });

  it('rejects a missing reporting asset id even when an amount exists', () => {
    const render = renderFor('1049.5', null, null);
    expect(render.kind).toBe('unavailable-reporting');
    expect(render.unavailableReason).toBe('missing-reporting-asset-id');
  });
});

describe('viewer display-currency conversion (pure display, explicit rate only)', () => {
  const quote = (rate?: string | null): DisplayCurrencyQuote => ({ currencyId: 'fiat:USD', rate });

  it('converts only with an explicit decimal rate', () => {
    const render = renderFor('1049.5', 'fiat:EUR', EUR_META, quote('1.2137'), USD_META);
    expect(render.kind).toBe('reporting-display-converted');
    expect(render.convertedText).toBe('$1,273.77');
    expect(render.convertedCode).toBe('USD');
    expect(render.rateApplied).toBe('1.2137');
    // Authoritative reporting figure is preserved (not overwritten).
    expect(render.reportingText).toBe('€1,049.50');
    expect(render.displayConversionUnavailableText).toBeNull();
  });

  it('does NOT convert when no rate is supplied and shows an explicit affordance', () => {
    for (const noRate of [undefined, null, '']) {
      const render = renderFor('1049.5', 'fiat:EUR', EUR_META, quote(noRate), USD_META);
      expect(render.kind).toBe('reporting-no-display-rate');
      expect(render.convertedText).toBeNull();
      expect(render.reportingText).toBe('€1,049.50');
      expect(render.displayConversionUnavailableText).toBe(DISPLAY_CONVERSION_UNAVAILABLE);
    }
  });

  it('does NOT convert on a malformed rate (never a $1 / 1:1 assumption)', () => {
    const render = renderFor('1049.5', 'fiat:EUR', EUR_META, quote('1.0.0'), USD_META);
    expect(render.kind).toBe('reporting-no-display-rate');
    expect(render.convertedText).toBeNull();
    expect(render.displayConversionUnavailableText).toBe(DISPLAY_CONVERSION_UNAVAILABLE);
  });

  it('does NOT convert when the display currency id is unrecognized', () => {
    const render = renderFor('1049.5', 'fiat:EUR', EUR_META, quote('1.2137'), null);
    expect(render.kind).toBe('reporting-no-display-rate');
    expect(render.convertedText).toBeNull();
  });

  it('does NOT convert when reporting is unavailable (nothing to convert)', () => {
    const render = renderFor(null, 'fiat:EUR', EUR_META, quote('1.2137'), USD_META);
    expect(render.kind).toBe('unavailable-reporting');
    expect(render.unavailableReason).toBe('no-reporting-amount');
  });
});

describe('decimal-string safety (never a JS float for canonical amounts)', () => {
  it('multiplies exactly with scaled-integer math', () => {
    expect(convertDecimalAmount('1234.56', '0.85')).toBe('1049.376');
    expect(convertDecimalAmount('0.1', '3')).toBe('0.3'); // not 0.30000000000000004
    expect(convertDecimalAmount('1.5', '1.5')).toBe('2.25');
    expect(convertDecimalAmount('-2', '3')).toBe('-6');
    expect(convertDecimalAmount('2', '-0.5')).toBe('-1');
  });

  it('keeps full precision on arbitrarily large amounts', () => {
    const huge = '123456789012345678901234567890.12';
    expect(convertDecimalAmount(huge, '1')).toBe(huge);
  });

  it('rejects non-decimal inputs instead of guessing', () => {
    expect(() => convertDecimalAmount('0.1', '1e2')).toThrow();
    expect(() => convertDecimalAmount('abc', '2')).toThrow();
    expect(isDecimalString('12.30')).toBe(true);
    expect(isDecimalString('-0.5')).toBe(true);
    expect(isDecimalString(0.1)).toBe(false);
    expect(isDecimalString('0.1.2')).toBe(false);
  });

  it('formats to the asset minor_units by truncation/padding, never rounding a float', () => {
    expect(formatDecimalAmount('1049.5', { minorUnits: 2 })).toBe('1,049.50');
    expect(formatDecimalAmount('1.23456', { minorUnits: 2 })).toBe('1.23');
    expect(formatDecimalAmount('1234.9', { minorUnits: 0 })).toBe('1,234');
    expect(formatDecimalAmount('5', { minorUnits: 2 })).toBe('5.00');
    expect(formatDecimalAmount('1234567.89', { group: false })).toBe('1234567.89');
    expect(formatDecimalAmount('1049.5', { minorUnits: null })).toBe('1,049.5');
  });

  it('decorates a symbol as a prefix and keeps the sign outside it', () => {
    expect(decorateAmountText('1,049.50', '€')).toBe('€1,049.50');
    expect(decorateAmountText('-1,049.50', '$')).toBe('-$1,049.50');
    expect(decorateAmountText('1.8432', null)).toBe('1.8432');
  });
});

describe('display never mutates the input value', () => {
  function deepFreeze<T>(value: T): T {
    if (value !== null && typeof value === 'object') {
      for (const key of Object.keys(value as object)) {
        deepFreeze((value as Record<string, unknown>)[key]);
      }
      Object.freeze(value);
    }
    return value;
  }

  it('composes from a deep-frozen value without throwing or changing it', () => {
    const valuation = deepFreeze<ReportingValuationLike>({
      reporting_asset_id: 'fiat:EUR',
      reporting_amount: '1049.5',
    });
    const frozenMeta = deepFreeze({ ...EUR_META });
    const frozenQuote = deepFreeze<DisplayCurrencyQuote>({ currencyId: 'fiat:USD', rate: '1.2137' });

    // Must not throw: any write to the frozen objects would throw in strict mode.
    const render = composeReportingDisplay({
      reportingAmount: valuation.reporting_amount,
      reportingAssetId: valuation.reporting_asset_id,
      assetMeta: frozenMeta,
      displayCurrencyQuote: frozenQuote,
      displayCurrencyMeta: USD_META,
    });

    expect(render.kind).toBe('reporting-display-converted');
    expect(valuation.reporting_amount).toBe('1049.5');
    expect(valuation.reporting_asset_id).toBe('fiat:EUR');
    expect(frozenMeta.symbol).toBe('€');
    expect(frozenQuote.rate).toBe('1.2137');
  });
});
