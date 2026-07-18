import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { FacetPanel, cohortMinimumFor } from './facet-panel';

describe('FacetPanel', () => {
  it('renders counts and a cohort-minimum suppression notice for withheld buckets', () => {
    const html = renderToStaticMarkup(
      <FacetPanel
        facets={[
          {
            field: 'geography.city',
            buckets: [
              { value: 'nyc', label: 'New York', count: 1200 },
              { value: 'sml', label: 'Smalltown', count: null },
            ],
          },
        ]}
      />,
    );
    expect(html).toContain('New York');
    expect(html).toContain('1200');
    expect(html).toContain('suppressed');
    expect(html).toContain('cohort &lt; 25'); // geography.city minimumCohortSize = 25 (HTML-escaped)
  });

  it('exposes the registry-declared cohort minimum', () => {
    expect(cohortMinimumFor('geography.city')).toBe(25);
    expect(cohortMinimumFor('risk.score')).toBeUndefined();
  });

  it('renders an empty message when there are no facets', () => {
    expect(renderToStaticMarkup(<FacetPanel facets={[]} />)).toContain('No facets');
  });
});
