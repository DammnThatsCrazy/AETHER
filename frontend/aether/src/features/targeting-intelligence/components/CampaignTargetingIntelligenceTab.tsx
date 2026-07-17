import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, LoadingState, useTimeContext} from '@aether/ui';
import {
  useCampaignJourneyDeltas,
  useCampaignTargetingIntelligence,
  useCreateTargetingExport,
  useTargetingExports,
} from '../use-targeting-intelligence';
import type {
  EligibilitySnapshotRecord,
  JourneyDeltaRecord,
  LeakageFindingRecord,
  ProviderMappingQualityRecord,
  TargetingIntentRecord,
  TargetingObservationRecord,
} from '../api';
import {
  CAMPAIGN_BOUNDARY_COPY,
  ClusterChipGroup,
  EvidenceChainSummary,
  ExportPackageDetail,
  LeakageSeverityBadge,
  NOT_CONFIGURED_DESCRIPTION,
  NOT_CONFIGURED_TITLE,
  formatCount,
  formatDateTime,
  formatRate,
  humanize,
} from './targeting-shared';

// ── Intended vs observed targeting ─────────────────────────────────────────────

function IntendedVsObservedSection({ intent, observation }: {
  readonly intent: TargetingIntentRecord | null;
  readonly observation: TargetingObservationRecord | null;
}) {
  const timeCtx = useTimeContext();
  if (!intent) {
    return (
      <EmptyState
        title="No targeting intent declared"
        description="Declare a targeting intent to compare intended targeting with observed reach."
      />
    );
  }

  const showReach = observation != null;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap text-xs text-text-muted">
        {intent.source && <Badge variant="default" size="sm">source: {humanize(intent.source)}</Badge>}
        {intent.graphMode && <Badge variant="default" size="sm">graph: {humanize(intent.graphMode)}</Badge>}
        <Badge variant="warning" size="sm">external execution required</Badge>
        {observation
          ? <span>Observed {formatDateTime(observation.observedAt, timeCtx)} via {observation.sourceProvider ?? 'unknown provider'}</span>
          : <span>No targeting observation yet — reach indicators appear after external execution is observed.</span>}
      </div>
      <ClusterChipGroup
        kind="include"
        clusterIds={intent.includeClusters ?? []}
        reachedClusterIds={observation?.reachedIncludedClusters ?? []}
        showReach={showReach}
      />
      <ClusterChipGroup
        kind="reference"
        clusterIds={intent.referenceClusters ?? []}
        reachedClusterIds={observation?.reachedReferenceClusters ?? []}
        showReach={showReach}
      />
      <ClusterChipGroup
        kind="exclude"
        clusterIds={intent.excludeClusters ?? []}
        reachedClusterIds={observation?.reachedExcludedClusters ?? []}
        showReach={showReach}
      />
      <ClusterChipGroup
        kind="holdout"
        clusterIds={intent.holdoutClusters ?? []}
        reachedClusterIds={observation?.reachedHoldoutClusters ?? []}
        showReach={showReach}
      />
    </div>
  );
}

// ── Eligibility snapshot summary ───────────────────────────────────────────────

function ThresholdStat({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="flex items-center justify-between text-xs font-mono">
      <span className="text-text-muted">{label}</span>
      <span className="text-text-primary">{value}</span>
    </div>
  );
}

function EligibilitySnapshotSection({ snapshot }: { readonly snapshot: EligibilitySnapshotRecord | null | undefined }) {
  const timeCtx = useTimeContext();
  if (!snapshot) {
    return (
      <EmptyState
        title="No eligibility snapshot"
        description="Eligibility snapshots freeze who was targetable at a point in time, enabling before/after comparison."
      />
    );
  }

  const memberTotal = Object.values(snapshot.clusterMemberCounts ?? {}).reduce((s, n) => s + n, 0);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap text-xs text-text-muted">
        <span className="font-mono text-text-primary">{snapshot.snapshotId}</span>
        <span>as of {formatDateTime(snapshot.asOf, timeCtx)}</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Eligible clusters', value: formatCount((snapshot.eligibleClusters ?? []).length, timeCtx) },
          { label: 'Excluded clusters', value: formatCount((snapshot.excludedClusters ?? []).length, timeCtx) },
          { label: 'Holdout clusters', value: formatCount((snapshot.holdoutClusters ?? []).length, timeCtx) },
          { label: 'Eligible members', value: formatCount(memberTotal, timeCtx) },
        ].map(({ label, value }) => (
          <div key={label} className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
            <p className="text-xs text-text-secondary">{label}</p>
            <p className="text-xl font-semibold text-text-primary mt-0.5">{value}</p>
          </div>
        ))}
      </div>
      <div className="space-y-1">
        <p className="text-xs font-medium text-text-muted uppercase tracking-wide">Thresholds</p>
        <ThresholdStat label="Identity confidence" value={formatRate(snapshot.identityConfidenceThreshold)} />
        <ThresholdStat label="Cluster membership" value={formatRate(snapshot.clusterMembershipThreshold)} />
        <ThresholdStat label="Path confidence" value={formatRate(snapshot.pathConfidenceThreshold)} />
        <ThresholdStat label="Evidence coverage" value={formatRate(snapshot.evidenceCoverageThreshold)} />
      </div>
    </div>
  );
}

// ── Exclusion leakage findings ─────────────────────────────────────────────────

function LeakageFindingRow({ finding }: { readonly finding: LeakageFindingRecord }) {
  const timeCtx = useTimeContext();
  return (
    <div className="border border-border-default rounded-md px-3 py-2.5 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap">
        <LeakageSeverityBadge severity={finding.severity} />
        <span className="text-sm font-medium text-text-primary font-mono">{finding.clusterId}</span>
        {finding.reasonCode && <Badge variant="default" size="sm">{humanize(finding.reasonCode)}</Badge>}
      </div>
      <div className="flex items-center gap-4 flex-wrap text-xs font-mono text-text-muted">
        <span>Leakage rate: <span className="text-danger">{formatRate(finding.leakageRate)}</span></span>
        <span>{formatCount(finding.reachedEntityCount, timeCtx)} of {formatCount(finding.excludedEntityCount, timeCtx)} excluded entities reached</span>
        <span>{(finding.evidenceRefs ?? []).length} evidence refs</span>
      </div>
      {(finding.likelyCauses ?? []).length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap text-xs">
          <span className="text-text-muted">Likely causes:</span>
          {(finding.likelyCauses ?? []).map(cause => (
            <Badge key={cause} variant="default" size="sm">{humanize(cause)}</Badge>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Provider mapping quality ───────────────────────────────────────────────────

function freshnessVariant(freshness: string): 'success' | 'warning' | 'danger' | 'default' {
  if (freshness === 'live') return 'success';
  if (freshness === 'recent') return 'default';
  if (freshness === 'stale') return 'warning';
  return 'danger';
}

function MappingQualitySection({ quality }: { readonly quality: ProviderMappingQualityRecord | null | undefined }) {
  const timeCtx = useTimeContext();
  if (!quality) {
    return (
      <EmptyState
        title="No provider mapping quality yet"
        description="Mapping quality appears once provider campaign data is observed and mapped."
      />
    );
  }

  return (
    <div className="space-y-3">
      {quality.blocksSuggestions && (
        <div className="border border-warning/30 bg-warning/10 rounded-md px-3 py-2 text-xs text-warning">
          Provider mapping confidence is too low — targeting suggestions are blocked until mapping quality improves.
        </div>
      )}
      <div className="flex items-center gap-2 flex-wrap text-xs">
        {quality.provider && <Badge variant="default" size="sm">{quality.provider}</Badge>}
        <Badge variant={freshnessVariant(quality.providerSyncFreshness ?? 'unknown')} size="sm">
          sync: {quality.providerSyncFreshness ?? 'unknown'}
        </Badge>
        <span className="text-text-muted">computed {formatDateTime(quality.computedAt, timeCtx)}</span>
      </div>
      <div className="space-y-1">
        <ThresholdStat label="Mapping rate" value={formatRate(quality.mappingRate)} />
        <ThresholdStat label="Touchpoint resolution" value={formatRate(quality.touchpointResolutionRate)} />
        <ThresholdStat label="Identity resolution" value={formatRate(quality.identityResolutionRate)} />
        <ThresholdStat label="Cluster assignment" value={formatRate(quality.clusterAssignmentRate)} />
        <ThresholdStat label="Quality score" value={formatRate(quality.qualityScore)} />
        <ThresholdStat label="Unresolved aliases" value={formatCount(quality.unresolvedAliasCount, timeCtx)} />
      </div>
      {(quality.reasons ?? []).length > 0 && (
        <ul className="list-disc list-inside space-y-0.5">
          {(quality.reasons ?? []).map(reason => (
            <li key={reason} className="text-xs text-text-secondary">{reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Journey deltas ─────────────────────────────────────────────────────────────

function JourneyDeltaRow({ delta }: { readonly delta: JourneyDeltaRecord }) {
  const timeCtx = useTimeContext();
  const stageDeltas = Object.entries(delta.populationStageDeltas ?? {});
  return (
    <div className="border border-border-default rounded-md px-3 py-2.5 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <span className="text-sm font-medium text-text-primary font-mono">{delta.clusterId}</span>
        {(delta.comparedToClusterIds ?? []).length > 0 && (
          <span className="text-text-muted">
            vs {(delta.comparedToClusterIds ?? []).join(', ')}
          </span>
        )}
      </div>
      <div className="flex items-center gap-4 flex-wrap text-xs font-mono text-text-muted">
        <span>Reached {formatCount(delta.reachedCount, timeCtx)}</span>
        <span>Engaged {formatCount(delta.engagedCount, timeCtx)}</span>
        <span>Converted {formatCount(delta.convertedCount, timeCtx)}</span>
        <span>Attributed {formatCount(delta.attributedCount, timeCtx)}</span>
        <span>Non-progressed {formatCount(delta.nonProgressedCount, timeCtx)}</span>
      </div>
      {stageDeltas.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          {stageDeltas.map(([stage, value]) => (
            <Badge key={stage} variant={value >= 0 ? 'success' : 'danger'} size="sm" className="font-mono">
              {humanize(stage)} {value >= 0 ? '+' : ''}{(value * 100).toFixed(1)}%
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Export packages section ────────────────────────────────────────────────────

function ExportPackagesSection({ campaignId, targetingIntentId }: {
  readonly campaignId: string;
  readonly targetingIntentId: string | null;
}) {
  const { exports, notConfigured, loading, error, refresh } = useTargetingExports();
  const { create, created, creating, error: createError } = useCreateTargetingExport();

  const campaignExports = exports.filter(
    pkg => pkg.campaignId === campaignId || (targetingIntentId !== null && pkg.targetingIntentId === targetingIntentId),
  );

  const handleExport = () => {
    if (!targetingIntentId) return;
    void create({ targetingIntentId }).then(pkg => {
      if (pkg) refresh();
    });
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle>Export packages</CardTitle>
          <Button
            variant="secondary"
            size="sm"
            disabled={creating || !targetingIntentId}
            onClick={handleExport}
            aria-label="Export recommendation package"
          >
            {creating ? 'Exporting…' : 'Export recommendation package'}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {createError && <ErrorState title="Failed to export recommendation package" message={createError} />}
        {created && (
          <div className="space-y-1.5">
            <p className="text-xs text-success">Recommendation package exported.</p>
            <ExportPackageDetail pkg={created} />
          </div>
        )}
        {loading && exports.length === 0 && !error && !notConfigured ? (
          <LoadingState lines={3} />
        ) : error ? (
          <ErrorState title="Failed to load export packages" message={error} onRetry={refresh} />
        ) : notConfigured ? (
          <EmptyState title={NOT_CONFIGURED_TITLE} description={NOT_CONFIGURED_DESCRIPTION} />
        ) : campaignExports.length === 0 && !created ? (
          <EmptyState
            title="No export packages yet"
            description="Exported recommendation packages for this campaign appear here."
          />
        ) : (
          campaignExports
            .filter(pkg => pkg.exportId !== created?.exportId)
            .map(pkg => <ExportPackageDetail key={pkg.exportId} pkg={pkg} />)
        )}
      </CardContent>
    </Card>
  );
}

// ── Tab ────────────────────────────────────────────────────────────────────────

export function CampaignTargetingIntelligenceTab({ campaignId }: { readonly campaignId: string }) {
  const { summary, notConfigured, loading, error, refresh } = useCampaignTargetingIntelligence(campaignId);
  const journeyDeltas = useCampaignJourneyDeltas(campaignId);

  if (loading && !summary && !error && !notConfigured) return <LoadingState lines={8} />;
  if (error) return <ErrorState title="Targeting intelligence unavailable" message={error} onRetry={refresh} />;
  if (notConfigured) return <EmptyState title={NOT_CONFIGURED_TITLE} description={NOT_CONFIGURED_DESCRIPTION} />;

  const intent = summary?.intents?.[0] ?? null;
  const latestSnapshot = summary?.latestSnapshots?.[0] ?? null;
  const observation = summary?.observations?.[0] ?? null;
  const leakage = summary?.leakageFindings ?? [];

  return (
    <div className="space-y-4">
      <div className="border border-border-default bg-surface-raised rounded-md px-3 py-2 text-xs text-text-secondary">
        {CAMPAIGN_BOUNDARY_COPY}
      </div>

      <Card>
        <CardHeader><CardTitle className="text-sm">Intended vs observed targeting</CardTitle></CardHeader>
        <CardContent>
          {summary
            ? <IntendedVsObservedSection intent={intent} observation={observation} />
            : (
              <EmptyState
                title="No targeting intelligence yet"
                description="Targeting intelligence appears once a targeting intent is declared or observed for this campaign."
              />
            )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Eligibility snapshot</CardTitle></CardHeader>
        <CardContent>
          <EligibilitySnapshotSection snapshot={latestSnapshot} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Exclusion leakage</CardTitle></CardHeader>
        <CardContent>
          {leakage.length === 0 ? (
            <EmptyState
              title="No exclusion leakage detected"
              description="Leakage findings appear when observed reach overlaps excluded clusters."
            />
          ) : (
            <div className="space-y-2">
              {leakage.map(finding => <LeakageFindingRow key={finding.findingId} finding={finding} />)}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Provider mapping quality</CardTitle></CardHeader>
        <CardContent>
          <MappingQualitySection quality={summary?.mappingQuality} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Journey-stage deltas</CardTitle></CardHeader>
        <CardContent>
          {journeyDeltas.loading && journeyDeltas.journeyDeltas.length === 0 && !journeyDeltas.error ? (
            <LoadingState lines={3} />
          ) : journeyDeltas.error ? (
            <ErrorState title="Journey deltas unavailable" message={journeyDeltas.error} onRetry={journeyDeltas.refresh} />
          ) : journeyDeltas.journeyDeltas.length === 0 ? (
            <EmptyState
              title="No journey deltas yet"
              description="Journey-stage deltas appear after observed reach and outcome windows are compared."
            />
          ) : (
            <div className="space-y-2">
              {journeyDeltas.journeyDeltas.map(delta => <JourneyDeltaRow key={delta.deltaId} delta={delta} />)}
            </div>
          )}
        </CardContent>
      </Card>

      {intent && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Evidence</CardTitle></CardHeader>
          <CardContent>
            <EvidenceChainSummary
              chain={{
                targetingIntentId: intent.id,
                eligibilitySnapshotId: latestSnapshot?.snapshotId,
                observationId: observation?.observationId,
              }}
            />
          </CardContent>
        </Card>
      )}

      <ExportPackagesSection campaignId={campaignId} targetingIntentId={intent?.id ?? null} />
    </div>
  );
}
