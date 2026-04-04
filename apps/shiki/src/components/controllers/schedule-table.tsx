import type { ControllerSchedule, ControllerDisplayMode, ControllerName } from '@shiki/types';
import { CONTROLLER_FUNCTIONAL_NAMES, CONTROLLER_EXPRESSIVE_NAMES } from '@shiki/types';
import { Badge, DataTable, Toggle } from '@shiki/components/system';
import { cn, formatRelativeTime, formatTimestamp } from '@shiki/lib/utils';

interface ScheduleTableProps {
  readonly schedules: readonly ControllerSchedule[];
  readonly displayMode: ControllerDisplayMode;
  readonly className?: string;
}

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

const typeVariant: Record<ControllerSchedule['type'], 'accent' | 'info' | 'warning'> = {
  cron: 'accent',
  interval: 'info',
  'one-shot': 'warning',
};

export function ScheduleTable({ schedules, displayMode, className }: ScheduleTableProps) {
  const columns = [
    {
      key: 'controller',
      header: 'Controller',
      render: (row: ControllerSchedule) => (
        <span className="font-mono">{controllerLabel(row.controller, displayMode)}</span>
      ),
      className: 'whitespace-nowrap',
    },
    {
      key: 'type',
      header: 'Type',
      render: (row: ControllerSchedule) => (
        <Badge variant={typeVariant[row.type]}>{row.type}</Badge>
      ),
    },
    {
      key: 'expression',
      header: 'Expression',
      render: (row: ControllerSchedule) => (
        <code className="text-[10px] bg-surface-sunken px-1.5 py-0.5 rounded font-mono">
          {row.expression}
        </code>
      ),
    },
    {
      key: 'nextRun',
      header: 'Next Run',
      render: (row: ControllerSchedule) => (
        <span className="font-mono" title={formatTimestamp(row.nextRun)}>
          {formatRelativeTime(row.nextRun)}
        </span>
      ),
    },
    {
      key: 'lastRun',
      header: 'Last Run',
      render: (row: ControllerSchedule) =>
        row.lastRun ? (
          <span className="font-mono" title={formatTimestamp(row.lastRun)}>
            {formatRelativeTime(row.lastRun)}
          </span>
        ) : (
          <span className="text-text-muted">&mdash;</span>
        ),
    },
    {
      key: 'enabled',
      header: 'Enabled',
      render: (row: ControllerSchedule) => (
        <Toggle checked={row.enabled} onChange={() => {}} disabled />
      ),
    },
    {
      key: 'missedFires',
      header: 'Missed',
      render: (row: ControllerSchedule) => (
        <span className={cn('font-mono', row.missedFires > 0 ? 'text-danger font-bold' : 'text-text-muted')}>
          {row.missedFires}
        </span>
      ),
      className: 'text-center',
    },
  ] as const;

  return (
    <div className={cn('space-y-3', className)}>
      <h3 className="text-sm font-medium text-text-primary font-mono">Schedules &amp; Wakeups</h3>
      <DataTable
        columns={columns}
        data={schedules}
        keyExtractor={(row) => row.id}
        emptyMessage="No schedules configured"
      />
    </div>
  );
}
