import type { Profile360DrillItem } from '@kyber/types';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from '@kyber/components/system';
import { formatRelativeTime } from '@kyber/lib/utils';

interface Profile360DrillStackProps {
  readonly stack: readonly Profile360DrillItem[];
  readonly onPop: () => void;
  readonly onReset: () => void;
}

export function Profile360DrillStack({ stack, onPop, onReset }: Profile360DrillStackProps) {
  if (stack.length === 0) return null;
  const active = stack[stack.length - 1];
  if (!active) return null;

  return (
    <Card className="border-blue-400/20">
      <CardHeader>
        <CardTitle>Profile360 Drill Stack</CardTitle>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onPop} className="text-xs">Back one</Button>
          <Button variant="ghost" onClick={onReset} className="text-xs">Reset</Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-1 text-xs">
          {stack.map((item, index) => (
            <span key={`${item.id}-${index}`} className="flex items-center gap-1">
              {index > 0 && <span className="text-neutral-600">/</span>}
              <Badge variant={index === stack.length - 1 ? 'accent' : 'default'} className="text-[10px]">{item.kind}</Badge>
              <span className={index === stack.length - 1 ? 'text-neutral-100' : 'text-neutral-500'}>{item.label}</span>
            </span>
          ))}
        </div>
        <div className="rounded border border-border-subtle bg-neutral-950/30 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-medium text-neutral-100">{active.label}</div>
              {active.subtitle && <div className="text-xs text-neutral-500">{active.subtitle}</div>}
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="default">{active.kind}</Badge>
              {active.timestamp && <span className="text-xs text-neutral-500">{formatRelativeTime(active.timestamp)}</span>}
            </div>
          </div>
          {Object.keys(active.metadata).length > 0 && (
            <pre className="mt-3 max-h-36 overflow-auto rounded bg-neutral-950 p-2 text-[11px] text-neutral-400">
              {JSON.stringify(active.metadata, null, 2)}
            </pre>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
