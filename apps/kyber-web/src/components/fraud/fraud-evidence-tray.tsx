import { useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState } from '@aether/ui';

interface FraudEvidenceTrayProps {
  readonly evidenceData?: unknown;
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function confidenceVariant(conf: unknown): 'default' | 'warning' | 'success' {
  const n = Number(conf ?? 0);
  if (n >= 0.8) return 'success';
  if (n >= 0.5) return 'warning';
  return 'default';
}

function signalVariant(signal: string): 'default' | 'warning' | 'danger' {
  if (['circular_transfer', 'split_merge', 'agentic_delegation_abuse'].includes(signal)) return 'danger';
  if (['shared_device', 'shared_ip', 'shared_wallet'].includes(signal)) return 'warning';
  return 'default';
}

type EvidenceItem = Record<string, unknown>;

export function FraudEvidenceTray({ evidenceData }: FraudEvidenceTrayProps) {
  const [expanded, setExpanded] = useState<string | null>(null);

  const raw = asRec(evidenceData);
  const items: EvidenceItem[] = Array.isArray(raw.evidence_refs)
    ? (raw.evidence_refs as EvidenceItem[])
    : Array.isArray(evidenceData)
    ? (evidenceData as EvidenceItem[])
    : [];

  if (items.length === 0) {
    return (
      <EmptyState
        title="No evidence"
        description="No evidence refs have been generated for this network yet."
      />
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {items.map((item, i) => {
        const id = fmt(item.id ?? i);
        const signal = fmt(item.type ?? item.signal);
        const confidence = item.confidence;
        const source = fmt(item.source);
        const isExpanded = expanded === id;
        const meta = asRec(item.metadata ?? item.detail ?? {});
        const metaEntries = Object.entries(meta).filter(([, v]) => v !== null && v !== undefined);

        return (
          <Card key={id}>
            <CardHeader
              className="cursor-pointer py-2 px-4"
              onClick={() => setExpanded(isExpanded ? null : id)}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Badge variant={signalVariant(signal)}>{signal}</Badge>
                  <span className="text-xs text-text-muted">{source}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={confidenceVariant(confidence)}>
                    {confidence !== undefined ? `${(Number(confidence) * 100).toFixed(0)}%` : '—'}
                  </Badge>
                  <span className="text-xs text-text-muted">{isExpanded ? '▲' : '▼'}</span>
                </div>
              </div>
            </CardHeader>
            {isExpanded && metaEntries.length > 0 && (
              <CardContent>
                <dl className="flex flex-col gap-1 text-xs">
                  {metaEntries.map(([k, v]) => (
                    <div key={k} className="flex justify-between">
                      <dt className="text-text-muted">{k}</dt>
                      <dd className="font-mono max-w-[200px] truncate">{String(v)}</dd>
                    </div>
                  ))}
                </dl>
              </CardContent>
            )}
          </Card>
        );
      })}
    </div>
  );
}
