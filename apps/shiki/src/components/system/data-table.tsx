import { cn } from '@shiki/lib/utils';
import type { ReactNode } from 'react';

interface Column<T> {
  readonly key: string;
  readonly header: string;
  readonly render: (row: T) => ReactNode;
  readonly className?: string;
}

interface DataTableProps<T> {
  readonly columns: readonly Column<T>[];
  readonly data: readonly T[];
  readonly keyExtractor: (row: T) => string;
  readonly onRowClick?: (row: T) => void;
  readonly className?: string;
  readonly emptyMessage?: string;
}

export function DataTable<T>({ columns, data, keyExtractor, onRowClick, className, emptyMessage = 'No data' }: DataTableProps<T>) {
  if (data.length === 0) {
    return <div className="text-text-muted text-xs text-center py-8 font-mono">{emptyMessage}</div>;
  }

  return (
    <div className={cn('overflow-auto', className)}>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border-default">
            {columns.map(col => (
              <th key={col.key} className={cn('text-left py-2 px-3 text-text-secondary font-medium', col.className)}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map(row => (
            <tr
              key={keyExtractor(row)}
              onClick={() => onRowClick?.(row)}
              className={cn(
                'border-b border-border-subtle',
                onRowClick && 'cursor-pointer hover:bg-surface-raised',
              )}
            >
              {columns.map(col => (
                <td key={col.key} className={cn('py-2 px-3 text-text-primary', col.className)}>
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
