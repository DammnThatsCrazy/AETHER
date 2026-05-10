import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ScrollArea } from '@kyber/components/system';
import { formatRelativeTime } from '@kyber/lib/utils';
import { useProfile360Store, profile360Actions } from '@kyber/features/profile360';
import type { Profile360Reference } from '@kyber/types';

interface Profile360DrillStackProps {
  readonly onOpen: (reference: Profile360Reference) => void;
}

export function Profile360DrillStack({ onOpen }: Profile360DrillStackProps) {
  const drillStack = useProfile360Store((state) => state.drillStack);

  if (drillStack.length === 0) {
    return null;
  }

  return (
    <div className="fixed right-4 top-20 bottom-4 z-30 flex items-stretch gap-2 pointer-events-none">
      {drillStack.map((item, index) => (
        <Card key={`${item.id}-${index}`} className="w-72 pointer-events-auto shadow-2xl bg-surface-default/95 backdrop-blur">
          <CardHeader>
            <div>
              <CardTitle className="truncate">{item.label}</CardTitle>
              <div className="mt-1 flex items-center gap-2">
                <Badge>{item.type}</Badge>
                <span className="text-[10px] text-text-muted font-mono">{formatRelativeTime(item.openedAt)}</span>
              </div>
            </div>
            <Button variant="ghost" size="sm" onClick={() => profile360Actions.popDrill(index - 1)}>
              ×
            </Button>
          </CardHeader>
          <CardContent>
            <ScrollArea maxHeight="calc(100vh - 220px)">
              <div className="space-y-3 text-xs">
                {item.description && <p className="text-text-secondary">{item.description}</p>}
                <div className="rounded border border-border-subtle bg-surface-raised p-2 font-mono text-[10px] text-text-muted break-all">
                  {item.id}
                </div>
                {item.metadata && Object.keys(item.metadata).length > 0 && (
                  <pre className="max-h-64 overflow-auto rounded bg-surface-raised p-2 text-[10px] text-text-secondary">
                    {JSON.stringify(item.metadata, null, 2)}
                  </pre>
                )}
                <Button size="sm" variant="secondary" onClick={() => onOpen(item)} className="w-full">
                  Open full profile
                </Button>
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
