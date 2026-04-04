import { useState } from 'react';
import type { ControllerObjective, ControllerDisplayMode, ControllerName } from '@shiki/types';
import { CONTROLLER_FUNCTIONAL_NAMES, CONTROLLER_EXPRESSIVE_NAMES } from '@shiki/types';
import { Badge, Select, DataTable, EmptyState } from '@shiki/components/system';
import { cn } from '@shiki/lib/utils';

interface ObjectiveBoardProps {
  readonly objectives: readonly ControllerObjective[];
  readonly displayMode: ControllerDisplayMode;
  readonly className?: string | undefined;
}

type ObjectiveStatus = ControllerObjective['status'] | 'all';

const STATUS_OPTIONS: readonly { value: string; label: string }[] = [
  { value: 'all', label: 'All Statuses' },
  { value: 'active', label: 'Active' },
  { value: 'blocked', label: 'Blocked' },
  { value: 'completed', label: 'Completed' },
  { value: 'deferred', label: 'Deferred' },
];

const statusVariant: Record<string, 'success' | 'danger' | 'default' | 'warning'> = {
  active: 'success',
  blocked: 'danger',
  completed: 'default',
  deferred: 'warning',
};

function controllerLabel(name: ControllerName, mode: ControllerDisplayMode): string {
  switch (mode) {
    case 'functional':
      return CONTROLLER_FUNCTIONAL_NAMES[name];
    case 'named':
      return name.toUpperCase();
    case 'expressive':
      return CONTROLLER_EXPRESSIVE_NAMES[name];
  }
}

export function ObjectiveBoard({ objectives, displayMode, className }: ObjectiveBoardProps) {
  const [statusFilter, setStatusFilter] = useState<ObjectiveStatus>('all');

  const filtered = statusFilter === 'all'
    ? objectives
    : objectives.filter((o) => o.status === statusFilter);

  const sorted = [...filtered].sort((a, b) => a.priority - b.priority);

  const columns = [
    {
      key: 'controller',
      header: 'Controller',
      render: (row: ControllerObjective) => (
        <span className="font-mono">{controllerLabel(row.controller, displayMode)}</span>
      ),
      className: 'whitespace-nowrap',
    },
    {
      key: 'title',
      header: 'Title',
      render: (row: ControllerObjective) => <span>{row.title}</span>,
    },
    {
      key: 'status',
      header: 'Status',
      render: (row: ControllerObjective) => (
        <Badge variant={statusVariant[row.status] ?? 'default'}>{row.status}</Badge>
      ),
      className: 'whitespace-nowrap',
    },
    {
      key: 'priority',
      header: 'Priority',
      render: (row: ControllerObjective) => (
        <span className={cn('font-mono', row.priority <= 1 && 'text-warning font-bold')}>
          P{row.priority}
        </span>
      ),
      className: 'text-center',
    },
    {
      key: 'blockedReason',
      header: 'Blocked Reason',
      render: (row: ControllerObjective) =>
        row.blockedReason ? (
          <span className="text-danger text-[10px]">{row.blockedReason}</span>
        ) : (
          <span className="text-text-muted">&mdash;</span>
        ),
    },
  ] as const;

  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-text-primary font-mono">Objectives</h3>
        <Select
          options={STATUS_OPTIONS as { value: string; label: string }[]}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v as ObjectiveStatus)}
        />
      </div>
      {sorted.length === 0 ? (
        <EmptyState title="No objectives" description={`No objectives matching "${statusFilter}" filter`} />
      ) : (
        <DataTable
          columns={columns}
          data={sorted}
          keyExtractor={(row) => row.id}
        />
      )}
    </div>
  );
}
