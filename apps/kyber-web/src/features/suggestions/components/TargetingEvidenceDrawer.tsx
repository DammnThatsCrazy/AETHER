import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from '@aether/ui';

type AnyRecord = Record<string, any>;

const TARGETING_CLASSES = new Set(['retargeting', 'campaign']);
const TARGETING_SUBJECT_KINDS = new Set(['targeting_intent', 'targeting_plan']);

/**
 * Tolerant detection of targeting-intelligence suggestions in the OODA
 * command center: source/service markers, a structured targeting payload, a
 * targeting subject kind, or a targeting suggestion class.
 */
export function isTargetingSuggestion(suggestion: AnyRecord): boolean {
  if (suggestion == null) return false;
  if (suggestion.source === 'targeting_intelligence') return true;
  if (suggestion.source_ref?.service === 'targeting_intelligence') return true;
  if (suggestion.targeting != null || suggestion.metadata?.targeting != null) return true;
  const subjectKind = suggestion.subject?.kind ?? suggestion.subject_kind;
  if (typeof subjectKind === 'string' && TARGETING_SUBJECT_KINDS.has(subjectKind)) return true;
  const suggestionClass = suggestion.suggestion_class ?? suggestion.suggestionClass;
  return typeof suggestionClass === 'string' && TARGETING_CLASSES.has(suggestionClass);
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === 'string');
}

function targetingPayload(suggestion: AnyRecord): AnyRecord {
  const t = suggestion.targeting ?? suggestion.metadata?.targeting;
  return t !== null && typeof t === 'object' ? (t as AnyRecord) : {};
}

const CHIP_GROUPS: ReadonlyArray<{
  label: string;
  keys: string[];
  variant: 'success' | 'danger' | 'info' | 'warning';
}> = [
  { label: 'Included clusters', keys: ['includeClusterIds', 'includeClusters', 'include_clusters'], variant: 'success' },
  { label: 'Reference clusters', keys: ['referenceClusterIds', 'referenceClusters', 'reference_clusters'], variant: 'info' },
  { label: 'Excluded clusters', keys: ['excludeClusterIds', 'excludeClusters', 'exclude_clusters'], variant: 'danger' },
  { label: 'Holdout clusters', keys: ['holdoutClusterIds', 'holdoutClusters', 'holdout_clusters'], variant: 'warning' },
];

const CHAIN_STAGES: ReadonlyArray<{ label: string; keys: string[] }> = [
  { label: 'Intent', keys: ['targetingIntentId', 'targeting_intent_id'] },
  { label: 'Snapshot', keys: ['eligibilitySnapshotId', 'eligibility_snapshot_id'] },
  { label: 'Observation', keys: ['observationId', 'observation_id'] },
  { label: 'Outcome', keys: ['outcomeSnapshotId', 'outcome_snapshot_id'] },
];

function chainRef(suggestion: AnyRecord, payload: AnyRecord, keys: string[]): string | null {
  const chain = (payload.evidenceChain ?? payload.evidence_chain ?? {}) as AnyRecord;
  for (const key of keys) {
    const value = chain[key] ?? payload[key] ?? suggestion[key];
    if (typeof value === 'string' && value) return value;
  }
  return null;
}

export interface TargetingEvidenceDrawerProps {
  readonly suggestion: AnyRecord;
  readonly onClose: () => void;
}

/**
 * Operator evidence drawer for targeting suggestions: cluster chips plus the
 * intent → snapshot → observation → outcome chain. Read-only — execution
 * always happens in the tenant's external campaign platform.
 */
export function TargetingEvidenceDrawer({ suggestion, onClose }: TargetingEvidenceDrawerProps) {
  const payload = targetingPayload(suggestion);
  const groups = CHIP_GROUPS
    .map(group => ({
      ...group,
      ids: group.keys.map(key => asStringArray(payload[key])).find(ids => ids.length > 0) ?? [],
    }))
    .filter(group => group.ids.length > 0);
  const evidence = (suggestion.evidence ?? []) as AnyRecord[];

  return (
    <div
      data-testid="targeting-evidence-drawer"
      className="fixed inset-y-0 right-0 z-40 w-[480px] max-w-full border-l border-border-default bg-surface-sunken shadow-xl overflow-y-auto p-4 space-y-4"
    >
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-mono font-bold text-text-primary">Targeting evidence</div>
          <div className="text-[10px] text-text-muted font-mono">
            {String(suggestion.suggestion_id ?? suggestion.id ?? '—')}
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>[x] Close</Button>
      </div>

      <div className="text-[10px] text-text-muted font-mono">
        Aether does not execute campaigns — execution happens in the tenant&apos;s external platforms.
      </div>

      <Card>
        <CardHeader><CardTitle>Cluster rules</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {groups.length === 0 ? (
            <p className="text-xs text-text-muted font-mono">No cluster rules attached to this suggestion.</p>
          ) : (
            groups.map(group => (
              <div key={group.label}>
                <p className="text-[10px] text-text-muted font-mono uppercase tracking-wide mb-1">{group.label}</p>
                <div className="flex items-center gap-1.5 flex-wrap">
                  {group.ids.map(id => (
                    <Badge key={id} variant={group.variant} size="sm" className="font-mono">{id}</Badge>
                  ))}
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Evidence chain</CardTitle></CardHeader>
        <CardContent>
          <div className="flex items-center gap-1.5 flex-wrap text-xs font-mono">
            {CHAIN_STAGES.map(({ label, keys }, index) => {
              const ref = chainRef(suggestion, payload, keys);
              return (
                <span key={label} className="flex items-center gap-1.5">
                  {index > 0 && <span className="text-text-muted">→</span>}
                  <span className={ref ? 'text-text-primary' : 'text-text-muted'}>
                    {label}: {ref ?? '—'}
                  </span>
                </span>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {evidence.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Evidence refs</CardTitle></CardHeader>
          <CardContent className="space-y-1">
            {evidence.slice(0, 10).map((ref, index) => (
              <div key={String(ref.id ?? index)} className="text-xs font-mono text-text-muted">
                {String(ref.id ?? '—')} <span className="text-text-secondary">({String(ref.source ?? ref.type ?? 'evidence')})</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
