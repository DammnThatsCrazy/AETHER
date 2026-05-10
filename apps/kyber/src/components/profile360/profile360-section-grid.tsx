import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from '@kyber/components/system';
import type { Profile360Reference, Profile360Section } from '@kyber/types';
import { cn } from '@kyber/lib/utils';

interface Profile360SectionGridProps {
  readonly sections: readonly Profile360Section[];
  readonly onDrill: (reference: Profile360Reference) => void;
}

function metricTone(tone?: string): string {
  if (tone === 'good') return 'text-success';
  if (tone === 'warning') return 'text-warning';
  if (tone === 'danger') return 'text-danger';
  return 'text-text-primary';
}

export function Profile360SectionGrid({ sections, onDrill }: Profile360SectionGridProps) {
  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      {sections.map((section) => (
        <Card key={section.id}>
          <CardHeader>
            <div>
              <CardTitle>{section.title}</CardTitle>
              {section.summary && <p className="mt-1 text-xs text-text-secondary">{section.summary}</p>}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {section.metrics && section.metrics.length > 0 && (
              <div className="grid grid-cols-3 gap-2">
                {section.metrics.map((metric) => (
                  <div key={metric.id} className="rounded border border-border-subtle bg-surface-raised p-3">
                    <div className="text-[10px] uppercase tracking-wide text-text-muted">{metric.label}</div>
                    <div className={cn('mt-1 text-lg font-semibold font-mono', metricTone(metric.tone))}>
                      {metric.value}{metric.unit ?? ''}
                    </div>
                    {metric.detail && <div className="mt-1 text-[10px] text-text-muted">{metric.detail}</div>}
                  </div>
                ))}
              </div>
            )}

            {section.references && section.references.length > 0 && (
              <div className="space-y-2">
                <div className="text-[10px] uppercase tracking-wide text-text-muted">Drill references</div>
                <div className="flex flex-wrap gap-2">
                  {section.references.map((reference) => (
                    <Button key={`${reference.type}-${reference.id}`} variant="secondary" size="sm" onClick={() => onDrill(reference)}>
                      <span className="truncate max-w-40">{reference.label}</span>
                      <Badge className="ml-2">{reference.type}</Badge>
                    </Button>
                  ))}
                </div>
              </div>
            )}

            {section.data && Object.keys(section.data).length > 0 && (
              <details className="group">
                <summary className="cursor-pointer text-xs text-accent">Inspect normalized data</summary>
                <pre className="mt-2 max-h-72 overflow-auto rounded bg-surface-raised p-3 text-[10px] text-text-secondary">
                  {JSON.stringify(section.data, null, 2)}
                </pre>
              </details>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
