import { cn } from '../utils/cn';
import {
  composeReportingDisplay,
  type DisplayCurrencyQuote,
  type ReportingValueRender,
  type ReportingValuationLike,
} from './reporting-value';
import { resolveCanonicalAssetDisplayMeta } from './reporting-asset-meta';

// =============================================================================
// Reporting-asset + viewer display-currency PRESENTATION (additive Wave 3).
//
// `ReportingValueDisplay` renders a value in its tenant REPORTING asset
// (canonical `reporting_amount` + `reporting_asset_id` resolved through the
// canonical asset metadata in `financial-assets.ts`) and — only when the caller
// supplies an explicit display-currency conversion rate — a PURE-DISPLAY viewer
// conversion. It composes with (never replaces) the USD-first `ValueDisplay`:
// this component is for envelopes that already report in a non-USD asset.
//
// Display NEVER mutates the stored fact: nothing here writes a formatted figure
// back into the value/valuation object, and an absent / malformed display rate
// renders the reporting amount plus an explicit "Display conversion
// unavailable" affordance rather than fabricating a $1 / 1:1 assumption. An
// absent reporting amount renders "Reporting unavailable" — never "0"/"$0".
//
// `buildReportingValueRender` is the headless render builder (no JSX), so the
// presentation logic is unit-testable without a DOM.
// =============================================================================

interface ReportingValueDisplayProps {
  /** The reporting valuation slice (USDValuation additive reporting fields).
   * Pass `envelope.valuation` — never the native object. */
  readonly value: ReportingValuationLike | null | undefined;
  /** Optional viewer display-currency request: canonical currency id + an
   * EXPLICIT decimal-string rate. Absent rate => conversion unavailable. */
  readonly displayCurrency?: DisplayCurrencyQuote | null | undefined;
  /** Override the unavailable message (default "Reporting unavailable"). */
  readonly fallback?: string | undefined;
  /** Right-align the stack (table cells / row-end amounts). */
  readonly align?: 'left' | 'right' | undefined;
  /** Hide the explicit "Display conversion unavailable" note. */
  readonly hideConversionNote?: boolean | undefined;
  readonly className?: string | undefined;
}

/** Figure text: decorated amount + display code, e.g. "€1,049.38 EUR". */
function amountFigure(amountText: string | null, code: string | null): string {
  if (!amountText) return '';
  return code ? `${amountText} ${code}` : amountText;
}

/** Build the reporting + display render for a value slice (headless/testable). */
export function buildReportingValueRender(
  value: ReportingValuationLike | null | undefined,
  displayCurrency?: DisplayCurrencyQuote | null | undefined,
  fallback?: string | undefined,
): ReportingValueRender {
  const reportingAssetId =
    value && value.reporting_asset_id !== null && value.reporting_asset_id !== undefined
      ? value.reporting_asset_id
      : null;
  const reportingAmount =
    value && value.reporting_amount !== null && value.reporting_amount !== undefined
      ? value.reporting_amount
      : null;

  return composeReportingDisplay({
    reportingAmount,
    reportingAssetId,
    assetMeta: resolveCanonicalAssetDisplayMeta(reportingAssetId),
    displayCurrencyQuote: displayCurrency ?? null,
    displayCurrencyMeta:
      displayCurrency && displayCurrency.currencyId.trim() !== ''
        ? resolveCanonicalAssetDisplayMeta(displayCurrency.currencyId)
        : null,
    fallbackLabel: fallback ?? null,
  });
}

/**
 * Reporting-asset value with optional pure-display viewer conversion.
 *
 * Primary / detail selection:
 *   - reporting amount absent            -> "Reporting unavailable" (never "0").
 *   - reporting amount present           -> reporting figure, e.g. "€1,049.38 EUR".
 *   - display currency w/ explicit rate  -> converted figure primary, e.g.
 *                                           "$1,273.82 USD", with the reporting
 *                                           figure as a muted "Reporting:" line.
 *   - display currency w/o a usable rate -> reporting figure + an explicit
 *                                           "Display conversion unavailable" note.
 */
export function ReportingValueDisplay({
  value,
  displayCurrency,
  fallback,
  align,
  hideConversionNote,
  className,
}: ReportingValueDisplayProps) {
  const render = buildReportingValueRender(value, displayCurrency, fallback);
  const reportingFigure = amountFigure(render.reportingText, render.reportingCode);

  let primary: string;
  let secondary: string | null = null;

  if (render.kind === 'reporting-display-converted') {
    // Viewer display currency was requested with an explicit rate: show the
    // converted figure as the headline and keep the authoritative reporting
    // figure as a muted drilldown.
    primary = amountFigure(render.convertedText, render.convertedCode);
    const report = reportingFigure;
    secondary = report ? `Reporting: ${report}` : null;
  } else if (render.kind === 'reporting-no-display-rate') {
    // A display currency was requested but no usable rate was supplied: show the
    // reporting amount and an explicit "conversion unavailable" affordance.
    primary = reportingFigure;
    if (!hideConversionNote && render.displayConversionUnavailableText) {
      secondary = render.displayConversionUnavailableText;
    }
  } else {
    // 'reporting' (amount present) and 'unavailable-reporting' (no attributable
    // amount) both surface `reportingFigure` — a real reporting figure, or the
    // explicit unavailable message (never a monetary zero).
    primary = reportingFigure;
  }

  return (
    <div className={cn('flex flex-col gap-0.5', align === 'right' && 'items-end', className)}>
      <span className="font-mono text-sm font-semibold text-text-primary">{primary}</span>
      {secondary && <span className="font-mono text-[10px] text-text-muted">{secondary}</span>}
    </div>
  );
}
