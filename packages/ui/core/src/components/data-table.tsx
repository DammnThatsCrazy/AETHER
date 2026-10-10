import type { ReactNode } from 'react';
import { cn } from '../utils/cn';

export type DataTableSortDirection = 'asc' | 'desc';

export interface DataTableSort {
  /** Canonical server field, not necessarily the presentation column key. */
  readonly field: string;
  readonly direction: DataTableSortDirection;
}

export interface DataTableQuery {
  readonly sort?: DataTableSort | undefined;
  /** Opaque server cursor. It must never be decoded or synthesized by the UI. */
  readonly cursor?: string | null | undefined;
  readonly limit?: number | undefined;
  /** Canonical serialized filter values sent to the server. */
  readonly filters?: Readonly<Record<string, string | readonly string[] | null>> | undefined;
}

/** Export always describes the complete filtered result, never just the visible cursor page. */
export type DataTableExportQuery = Omit<DataTableQuery, 'cursor' | 'limit'>;

export interface DataTableColumn<T> {
  readonly key: string;
  readonly header: ReactNode;
  readonly render: (row: T) => ReactNode;
  readonly className?: string;
  /** Server field to request when this header is sorted. */
  readonly sortField?: string;
  readonly headerLabel?: string;
}

export interface DataTableCursorPage {
  /** Number of rows in this response, kept separate from the full result count. */
  readonly returned: number;
  /** Total number matching the server query, when the backend can provide it. */
  readonly total?: number | null;
  readonly nextCursor?: string | null;
  readonly previousCursor?: string | null;
  readonly onNext?: ((cursor: string) => void) | undefined;
  readonly onPrevious?: ((cursor: string) => void) | undefined;
}

export interface DataTableSelection {
  readonly selectedKeys: readonly string[];
  readonly onSelectionChange: (keys: readonly string[]) => void;
  readonly getRowLabel?: ((rowKey: string) => string) | undefined;
}

export interface DataTableExport {
  readonly query: DataTableExportQuery;
  readonly onExport: (query: DataTableExportQuery) => void;
  readonly label?: string;
  readonly disabled?: boolean;
}

export interface DataTableProps<T> {
  readonly columns: readonly DataTableColumn<T>[];
  readonly data: readonly T[];
  readonly keyExtractor: (row: T) => string;
  readonly onRowClick?: (row: T) => void;
  readonly className?: string;
  readonly emptyMessage?: string;
  /** Accessible table name. Required by new production surfaces. */
  readonly caption?: string;
  /** Controlled server sort. DataTable never sorts rows locally. */
  readonly sort?: DataTableSort | undefined;
  readonly onSortChange?: ((sort: DataTableSort) => void) | undefined;
  readonly page?: DataTableCursorPage | undefined;
  readonly selection?: DataTableSelection | undefined;
  readonly exportAction?: DataTableExport | undefined;
  readonly loading?: boolean;
}

export function nextDataTableSort(
  current: DataTableSort | undefined,
  field: string,
): DataTableSort {
  return {
    field,
    direction: current?.field === field && current.direction === 'asc' ? 'desc' : 'asc',
  };
}

export function toggleDataTableSelection(
  selectedKeys: readonly string[],
  key: string,
  selected: boolean,
): readonly string[] {
  const next = new Set(selectedKeys);
  if (selected) next.add(key);
  else next.delete(key);
  return [...next];
}

export function toggleDataTablePageSelection(
  selectedKeys: readonly string[],
  pageKeys: readonly string[],
  selected: boolean,
): readonly string[] {
  const next = new Set(selectedKeys);
  for (const key of pageKeys) {
    if (selected) next.add(key);
    else next.delete(key);
  }
  return [...next];
}

export function DataTable<T>({
  columns,
  data,
  keyExtractor,
  onRowClick,
  className,
  emptyMessage = 'No data',
  caption,
  sort,
  onSortChange,
  page,
  selection,
  exportAction,
  loading = false,
}: DataTableProps<T>) {
  const pageKeys = data.map(keyExtractor);
  const selected = new Set(selection?.selectedKeys ?? []);
  const selectedOnPage = pageKeys.filter((key) => selected.has(key)).length;
  const allPageSelected = pageKeys.length > 0 && selectedOnPage === pageKeys.length;
  const somePageSelected = selectedOnPage > 0 && !allPageSelected;
  const returned = page?.returned ?? data.length;

  const controls = page || exportAction || selection;
  const resultSummary =
    page?.total == null ? `${returned} returned` : `${returned} returned of ${page.total} total`;

  return (
    <div className={cn('overflow-auto', className)} aria-busy={loading || undefined}>
      {controls && (
        <div className="flex flex-wrap items-center justify-between gap-2 px-1 py-2 text-[11px] text-text-muted">
          <span role="status" aria-live="polite">
            {resultSummary}
            {selection && selected.size > 0 ? ` · ${selected.size} selected` : ''}
          </span>
          {exportAction && (
            <button
              type="button"
              className="rounded border border-border-default px-2 py-1 text-text-secondary hover:bg-surface-raised disabled:cursor-not-allowed disabled:opacity-50"
              disabled={loading || exportAction.disabled}
              onClick={() => exportAction.onExport(exportAction.query)}
            >
              {exportAction.label ?? 'Export results'}
            </button>
          )}
        </div>
      )}
      <table className="w-full text-xs">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-border-default">
            {selection && (
              <th scope="col" className="w-9 px-3 py-2 text-left">
                <input
                  type="checkbox"
                  aria-label="Select all returned rows"
                  checked={allPageSelected}
                  ref={(node) => {
                    if (node) node.indeterminate = somePageSelected;
                  }}
                  disabled={loading || pageKeys.length === 0}
                  onChange={(event) =>
                    selection.onSelectionChange(
                      toggleDataTablePageSelection(
                        selection.selectedKeys,
                        pageKeys,
                        event.currentTarget.checked,
                      ),
                    )
                  }
                />
              </th>
            )}
            {columns.map((col) => {
              const activeSort = col.sortField && sort?.field === col.sortField ? sort.direction : undefined;
              return (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={activeSort === 'asc' ? 'ascending' : activeSort === 'desc' ? 'descending' : undefined}
                  className={cn('text-left py-2 px-3 text-text-secondary font-medium', col.className)}
                >
                  {col.sortField && onSortChange ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 hover:text-text-primary disabled:cursor-not-allowed"
                      disabled={loading}
                      aria-label={`Sort by ${col.headerLabel ?? (typeof col.header === 'string' ? col.header : col.key)}`}
                      onClick={() => onSortChange(nextDataTableSort(sort, col.sortField!))}
                    >
                      {col.header}
                      <span aria-hidden>{activeSort === 'asc' ? '↑' : activeSort === 'desc' ? '↓' : '↕'}</span>
                    </button>
                  ) : col.header}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {data.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length + (selection ? 1 : 0)}
                className="text-text-muted text-xs text-center py-8 font-mono"
              >
                {loading ? 'Loading…' : emptyMessage}
              </td>
            </tr>
          ) : data.map((row) => {
            const rowKey = keyExtractor(row);
            return (
              <tr
                key={rowKey}
                onClick={() => onRowClick?.(row)}
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
                tabIndex={onRowClick ? 0 : undefined}
                className={cn(
                  'border-b border-border-subtle',
                  onRowClick && 'cursor-pointer hover:bg-surface-raised focus:outline-none focus:ring-2 focus:ring-inset focus:ring-accent',
                )}
              >
                {selection && (
                  <td className="w-9 px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label={`Select ${selection.getRowLabel?.(rowKey) ?? `row ${rowKey}`}`}
                      checked={selected.has(rowKey)}
                      disabled={loading}
                      onClick={(event) => event.stopPropagation()}
                      onChange={(event) =>
                        selection.onSelectionChange(
                          toggleDataTableSelection(
                            selection.selectedKeys,
                            rowKey,
                            event.currentTarget.checked,
                          ),
                        )
                      }
                    />
                  </td>
                )}
                {columns.map((col) => (
                  <td key={col.key} className={cn('py-2 px-3 text-text-primary', col.className)}>
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      {page && (
        <nav className="flex items-center justify-end gap-2 px-1 py-2" aria-label={`${caption ?? 'Table'} pagination`}>
          <button
            type="button"
            className="rounded border border-border-default px-2 py-1 text-[11px] text-text-secondary disabled:cursor-not-allowed disabled:opacity-50"
            disabled={loading || !page.previousCursor || !page.onPrevious}
            onClick={() => {
              if (page.previousCursor) page.onPrevious?.(page.previousCursor);
            }}
          >
            Previous
          </button>
          <button
            type="button"
            className="rounded border border-border-default px-2 py-1 text-[11px] text-text-secondary disabled:cursor-not-allowed disabled:opacity-50"
            disabled={loading || !page.nextCursor || !page.onNext}
            onClick={() => {
              if (page.nextCursor) page.onNext?.(page.nextCursor);
            }}
          >
            Next
          </button>
        </nav>
      )}
    </div>
  );
}
