import { Badge, Button, ErrorState } from '@aether/ui';
import { useCreateTargetingExport } from '../use-targeting-intelligence';
import {
  ClusterChipGroup,
  EvidenceChainSummary,
  ExportPackageDetail,
  EXTERNAL_EXECUTION_REQUIRED_COPY,
} from './targeting-shared';
import type { ClusterRuleKind, EvidenceChainRefs } from './targeting-shared';

type AnyRecord = Record<string, any>;

const TARGETING_CLASSES = new Set(['retargeting', 'campaign']);
const TARGETING_SUBJECT_KINDS = new Set(['targeting_intent', 'targeting_plan']);

/**
 * Tolerant detection of targeting-class suggestions. The backend emits
 * suggestion_class "retargeting" for targeting intelligence findings; a
 * structured `targeting` payload or targeting subject kind also qualifies.
 */
export function isTargetingSuggestion(suggestion: AnyRecord): boolean {
  if (suggestion == null) return false;
  const source = suggestion.source ?? suggestion.suggestion_source;
  if (source === 'targeting_intelligence') return true;
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

function clusterIds(payload: AnyRecord, kind: ClusterRuleKind): string[] {
  const keys: Record<ClusterRuleKind, string[]> = {
    include: ['includeClusterIds', 'includeClusters', 'include_clusters'],
    exclude: ['excludeClusterIds', 'excludeClusters', 'exclude_clusters'],
    reference: ['referenceClusterIds', 'referenceClusters', 'reference_clusters'],
    holdout: ['holdoutClusterIds', 'holdoutClusters', 'holdout_clusters'],
  };
  for (const key of keys[kind]) {
    const found = asStringArray(payload[key]);
    if (found.length > 0) return found;
  }
  return [];
}

function evidenceChain(suggestion: AnyRecord, payload: AnyRecord): EvidenceChainRefs {
  const chain = (payload.evidenceChain ?? payload.evidence_chain ?? {}) as AnyRecord;
  return {
    targetingIntentId: chain.targetingIntentId ?? payload.targetingIntentId ?? suggestion.targeting_intent_id ?? null,
    eligibilitySnapshotId: chain.eligibilitySnapshotId ?? payload.eligibilitySnapshotId ?? suggestion.eligibility_snapshot_id ?? null,
    observationId: chain.observationId ?? payload.observationId ?? suggestion.observation_id ?? null,
    outcomeSnapshotId: chain.outcomeSnapshotId ?? payload.outcomeSnapshotId ?? suggestion.outcome_snapshot_id ?? null,
  };
}

interface TargetingSuggestionSectionProps {
  readonly suggestion: AnyRecord;
}

/**
 * Additive targeting card content: cluster chips, the intent → snapshot →
 * observation → outcome evidence chain, and the implementation-package
 * export action. Aether never executes the exported package.
 */
export function TargetingSuggestionSection({ suggestion }: TargetingSuggestionSectionProps) {
  const { create, created, creating, error } = useCreateTargetingExport();

  const payload = targetingPayload(suggestion);
  const suggestionId = String(suggestion.id ?? suggestion.suggestion_id ?? '');
  const chain = evidenceChain(suggestion, payload);

  const groups = (['include', 'reference', 'exclude', 'holdout'] as const)
    .map(kind => ({ kind, ids: clusterIds(payload, kind) }))
    .filter(group => group.ids.length > 0);

  const handleExport = () => {
    if (!suggestionId) return;
    void create({ suggestionId });
  };

  return (
    <div className="border-t border-border-default pt-3 space-y-3" data-testid="targeting-suggestion-section">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant="accent" size="sm">Targeting</Badge>
        <Badge variant="warning" size="sm">{EXTERNAL_EXECUTION_REQUIRED_COPY}</Badge>
      </div>

      {groups.length > 0 && (
        <div className="space-y-2">
          {groups.map(({ kind, ids }) => (
            <ClusterChipGroup key={kind} kind={kind} clusterIds={ids} showReach={false} />
          ))}
        </div>
      )}

      <EvidenceChainSummary chain={chain} />

      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          disabled={creating || !suggestionId}
          onClick={handleExport}
          aria-label="Export implementation package"
        >
          {creating ? 'Exporting…' : 'Export implementation package'}
        </Button>
      </div>

      {error && <ErrorState title="Failed to export implementation package" message={error} />}
      {created && (
        <div className="space-y-1.5">
          <p className="text-xs text-success">Implementation package exported.</p>
          <ExportPackageDetail pkg={created} />
        </div>
      )}
    </div>
  );
}
