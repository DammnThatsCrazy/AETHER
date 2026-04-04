import { Card, CardHeader, CardTitle, CardContent, TerminalSeparator } from '@shiki/components/system';

interface CommandBriefPanelProps {
  readonly brief: string;
  readonly timestamp?: string;
  readonly className?: string;
}

export function CommandBriefPanel({ brief, timestamp, className }: CommandBriefPanelProps) {
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>
          <span className="font-mono">\u2605</span> Command Brief
        </CardTitle>
        {timestamp && <span className="text-[10px] text-text-muted">{timestamp}</span>}
      </CardHeader>
      <CardContent>
        <TerminalSeparator />
        <div className="font-mono text-xs text-text-primary leading-relaxed whitespace-pre-wrap bg-surface-sunken p-3 rounded border border-border-subtle">
          {brief}
        </div>
        <TerminalSeparator />
      </CardContent>
    </Card>
  );
}
