import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { FilterDisposition } from '@aether/shared/exploration-contract';
import { FilterDispositionBadge, dispositionStyle } from './disposition-badge';

const FOUR: FilterDisposition[] = ['applied', 'translated', 'unsupported', 'suppressed'];

describe('FilterDispositionBadge', () => {
  it('renders each of the four disposition states with a distinct label', () => {
    const rendered = FOUR.map((d) => renderToStaticMarkup(<FilterDispositionBadge disposition={d} />));
    expect(new Set(rendered).size).toBe(4);
    expect(rendered[0]).toContain('Applied');
    expect(rendered[1]).toContain('Translated');
    expect(rendered[2]).toContain('Unsupported');
    expect(rendered[3]).toContain('Suppressed');
  });

  it('maps the four dispositions to distinct badge variants', () => {
    const variants = FOUR.map((d) => dispositionStyle(d).variant);
    expect(new Set(variants).size).toBe(4);
  });

  it('exposes a machine-readable disposition marker', () => {
    const html = renderToStaticMarkup(<FilterDispositionBadge disposition="suppressed" />);
    expect(html).toContain('data-disposition="suppressed"');
  });

  it('surfaces the reason as a tooltip', () => {
    const html = renderToStaticMarkup(
      <FilterDispositionBadge disposition="translated" reason="mapped to risk.score" />,
    );
    expect(html).toContain('title="mapped to risk.score"');
  });
});
