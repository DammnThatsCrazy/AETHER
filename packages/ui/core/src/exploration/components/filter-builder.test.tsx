// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/react';
import type { FilterExpression } from '@aether/shared/graph-contract';
import { FilterBuilder } from './filter-builder';
import { filterFieldsForSurface } from '../registry';

afterEach(cleanup);

// `geo` supports the `geography` category; `cluster360` does not — so a field
// selected on `geo` (e.g. geography.city) is invalid on `cluster360`.
const GEO_FIELD_IDS = new Set(filterFieldsForSurface('geo').map((f) => f.id));
const CLUSTER_FIELD_IDS = new Set(filterFieldsForSurface('cluster360').map((f) => f.id));

function fieldSelect(container: HTMLElement): HTMLSelectElement {
  // The first <select> is the Field picker.
  return container.querySelectorAll('select')[0] as HTMLSelectElement;
}

describe('FilterBuilder surface changes', () => {
  it('clamps a stale field selection to the new surface registry', () => {
    const { container, rerender } = render(<FilterBuilder surface="geo" onAdd={() => undefined} />);
    const geoField = fieldSelect(container);
    // Select a geography-only field that cluster360 cannot offer.
    fireEvent.change(geoField, { target: { value: 'geography.city' } });
    expect(geoField.value).toBe('geography.city');
    expect(GEO_FIELD_IDS.has('geography.city')).toBe(true);
    expect(CLUSTER_FIELD_IDS.has('geography.city')).toBe(false);

    // Cross-surface nav WITHOUT remount: the stale field must be dropped.
    rerender(<FilterBuilder surface="cluster360" onAdd={() => undefined} />);
    const clusterField = fieldSelect(container);
    expect(clusterField.value).not.toBe('geography.city');
    expect(CLUSTER_FIELD_IDS.has(clusterField.value)).toBe(true);
  });

  it('never emits a field the current surface does not support after a surface change', () => {
    const added: FilterExpression[] = [];
    const { container, rerender } = render(
      <FilterBuilder surface="geo" onAdd={(e) => added.push(e)} />,
    );
    fireEvent.change(fieldSelect(container), { target: { value: 'geography.city' } });

    rerender(<FilterBuilder surface="cluster360" onAdd={(e) => added.push(e)} />);
    // Provide a value and add — the emitted expression must be cluster360-valid.
    const valueInput = container.querySelector('input') as HTMLInputElement | null;
    if (valueInput) fireEvent.change(valueInput, { target: { value: 'x' } });
    const addBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.includes('Add filter'),
    ) as HTMLButtonElement;
    fireEvent.click(addBtn);

    expect(added.length).toBe(1);
    const emitted = added.at(0);
    if (!emitted) throw new Error('expected a filter to be emitted');
    expect(CLUSTER_FIELD_IDS.has(emitted.field)).toBe(true);
    expect(emitted.field).not.toBe('geography.city');
  });
});
