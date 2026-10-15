import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  DataTable,
  nextDataTableSort,
  toggleDataTablePageSelection,
  toggleDataTableSelection,
  type DataTableColumn,
} from './data-table';

interface Row {
  readonly id: string;
  readonly name: string;
}

const columns: readonly DataTableColumn<Row>[] = [
  {
    key: 'name',
    header: 'Name',
    render: (row) => row.name,
    sortField: 'profile.name',
  },
];

describe('DataTable server contract', () => {
  it('toggles a server sort without sorting data locally', () => {
    expect(nextDataTableSort(undefined, 'profile.name')).toEqual({
      field: 'profile.name',
      direction: 'asc',
    });
    expect(nextDataTableSort({ field: 'profile.name', direction: 'asc' }, 'profile.name')).toEqual({
      field: 'profile.name',
      direction: 'desc',
    });
    expect(nextDataTableSort({ field: 'created_at', direction: 'desc' }, 'profile.name')).toEqual({
      field: 'profile.name',
      direction: 'asc',
    });
  });

  it('preserves selection across cursor pages', () => {
    expect(toggleDataTableSelection(['off-page'], 'visible', true)).toEqual(['off-page', 'visible']);
    expect(toggleDataTablePageSelection(['off-page', 'a'], ['a', 'b'], false)).toEqual(['off-page']);
    expect(toggleDataTablePageSelection(['off-page'], ['a', 'b'], true)).toEqual([
      'off-page',
      'a',
      'b',
    ]);
  });

  it('renders returned-vs-total truth, accessible sort, selection, cursor, and export controls', () => {
    const html = renderToStaticMarkup(
      <DataTable
        caption="Profiles"
        columns={columns}
        data={[{ id: '1', name: 'Alpha' }]}
        keyExtractor={(row) => row.id}
        sort={{ field: 'profile.name', direction: 'asc' }}
        onSortChange={() => undefined}
        selection={{ selectedKeys: ['1', 'off-page'], onSelectionChange: () => undefined }}
        page={{
          returned: 1,
          total: 41,
          nextCursor: 'opaque-next',
          onNext: () => undefined,
        }}
        exportAction={{
          query: { sort: { field: 'profile.name', direction: 'asc' }, filters: { segment: 'vip' } },
          onExport: () => undefined,
        }}
      />,
    );

    expect(html).toContain('<caption class="sr-only">Profiles</caption>');
    expect(html).toContain('1 returned of 41 total · 2 selected');
    expect(html).toContain('aria-sort="ascending"');
    expect(html).toContain('aria-label="Select all returned rows"');
    expect(html).toContain('aria-label="Profiles pagination"');
    expect(html).toContain('Export results');
    expect(html).not.toContain('opaque-next');
  });

  it('keeps an empty table structurally accessible and discloses loading', () => {
    const html = renderToStaticMarkup(
      <DataTable
        caption="Profiles"
        columns={columns}
        data={[]}
        keyExtractor={(row) => row.id}
        loading
      />,
    );

    expect(html).toContain('aria-busy="true"');
    expect(html).toContain('Loading');
    expect(html).toContain('colSpan="1"');
  });
});
