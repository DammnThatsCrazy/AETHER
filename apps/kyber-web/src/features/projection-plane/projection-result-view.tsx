/**
 * Presentational renderers for the intelligence-projection plane's read-only
 * ProjectionResult payload (risk360 / fraud360 operator surfaces).
 *
 * Purely presentational: these components never fetch, never fabricate content,
 * and never convert a state label into a stronger epistemic claim than the
 * payload reports. `content` is opaque — a string, structured object, array, or
 * null — and every shape is rendered honestly (missing content renders as an
 * empty state, never as a silent assertion).
 */

import type { ReactNode } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@aether/ui';
import {
  displayText,
  hypothesisTone,
  isHypothesisLike,
  sectionHasContent,
  sectionTone,
  type BadgeTone,
  type ProjectionClaimModel,
  type ProjectionDependencyModel,
  type ProjectionResultModel,
  type ProjectionSectionModel,
} from './types';

const MAX_DEPTH = 4;

function asObject(value: unknown): Readonly<Record<string, unknown>> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Readonly<Record<string, unknown>>)
    : null;
}

function stringArray(value: unknown): readonly string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

function numberLabel(value: unknown): string | null {
  return typeof value === 'number' && Number.isFinite(value) ? String(Math.round(value * 1000) / 1000) : null;
}

function stateBadge(value: unknown, tone: (state: unknown) => BadgeTone): ReactNode {
  if (value === null || value === undefined || value === '') return null;
  return <Badge variant={tone(value)}>{String(value)}</Badge>;
}

function evidenceIds(value: unknown): readonly string[] {
  if (!Array.isArray(value)) return [];
  const ids: string[] = [];
  for (const item of value) {
    const rec = asObject(item);
    const id = rec
      ? typeof rec.id === 'string'
        ? rec.id
        : typeof rec.source_id === 'string'
          ? rec.source_id
          : typeof rec.kind === 'string'
            ? `${rec.kind}:${displayText(rec.value, '')}`
            : ''
      : '';
    if (id) ids.push(id);
  }
  return ids;
}

function jsonPreview(value: unknown): string {
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

function hypothesisKey(item: unknown, index: number): string {
  const rec = asObject(item);
  const id = rec ? rec.hypothesisId ?? rec.id : undefined;
  return typeof id === 'string' && id ? id : `h-${index}`;
}

/** A fraud finding-candidate / material hypothesis, surfaced as a card + badges. */
export function ProjectionHypothesisCard({ value }: { value: unknown }) {
  const rec = asObject(value);
  if (!rec) return null;
  const id = displayText(rec.hypothesisId ?? rec.id, '—');
  const materiality = numberLabel(rec.materiality);
  const confidence = numberLabel(rec.confidence);
  const patterns = stringArray(rec.matchedPatternIds);
  const evidence = evidenceIds(rec.evidenceRefs);

  return (
    <div className="rounded-md border border-border-subtle bg-surface-sunken/40 p-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-xs font-medium text-text-primary">{id}</span>
        {rec.family !== undefined && <Badge variant="default">{displayText(rec.family)}</Badge>}
        {stateBadge(rec.state, hypothesisTone)}
        {stateBadge(rec.claimState, hypothesisTone)}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-text-secondary">
        {materiality !== null && <span>materiality {materiality}</span>}
        {confidence !== null && <span>confidence {confidence}</span>}
        {patterns.length > 0 && (
          <span className="flex flex-wrap items-center gap-1">
            <span className="text-text-muted">patterns</span>
            {patterns.map(p => (
              <Badge key={p} variant="info" size="sm">{p}</Badge>
            ))}
          </span>
        )}
        {evidence.length > 0 && <span>evidence {evidence.length}</span>}
      </div>
      {evidence.length > 0 && (
        <p className="mt-1.5 break-all font-mono text-[10px] leading-relaxed text-text-muted">
          {evidence.join(' · ')}
        </p>
      )}
    </div>
  );
}

/** Render an array value, favoring hypothesis-like entries as cards. */
function ProjectionArray({ value, depth }: { value: readonly unknown[]; depth: number }): ReactNode {
  if (value.length === 0) return <span className="text-xs text-text-muted">Empty</span>;
  if (depth > MAX_DEPTH) {
    const preview = jsonPreview(value);
    return <code className="block break-all font-mono text-[10px] text-text-muted">{preview.slice(0, 600)}</code>;
  }

  const allHypotheses = value.every(isHypothesisLike);
  if (allHypotheses) {
    return (
      <div className="space-y-2">
        {value.map((item, i) => (
          <ProjectionHypothesisCard key={hypothesisKey(item, i)} value={item} />
        ))}
      </div>
    );
  }

  if (value.every(v => typeof v === 'string' || typeof v === 'number')) {
    return (
      <ul className="list-inside list-disc space-y-0.5 text-xs text-text-secondary">
        {value.map((item, i) => (
          <li key={i}>{String(item)}</li>
        ))}
      </ul>
    );
  }

  return (
    <div className="space-y-1.5">
      {value.map((item, i) => (
        <ProjectionContent key={`row-${i}`} value={item} depth={depth + 1} />
      ))}
    </div>
  );
}

/** Render an object value as an honest key/value definition list. */
function ProjectionObject({ value, depth }: { value: Readonly<Record<string, unknown>>; depth: number }): ReactNode {
  const entries = Object.entries(value);
  if (entries.length === 0) return <span className="text-xs text-text-muted">Empty</span>;
  if (depth > MAX_DEPTH) {
    const preview = jsonPreview(value);
    return <code className="block break-all font-mono text-[10px] text-text-muted">{preview.slice(0, 600)}</code>;
  }

  return (
    <dl className="space-y-2">
      {entries.map(([key, child]) => (
        <div key={key} className="grid grid-cols-[minmax(96px,180px)_1fr] items-start gap-2">
          <dt className="break-all pt-0.5 font-mono text-[10px] uppercase tracking-wide text-text-muted">{key}</dt>
          <dd className="min-w-0">
            {isHypothesisLike(child) ? (
              <ProjectionHypothesisCard value={child} />
            ) : (
              <ProjectionContent value={child} depth={depth + 1} />
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Render an opaque ProjectionSection `content` value (string | object | array). */
export function ProjectionContent({ value, depth = 0 }: { value: unknown; depth?: number }): ReactNode {
  if (value === null || value === undefined) {
    return <span className="text-xs text-text-muted">No content</span>;
  }
  if (Array.isArray(value)) return <ProjectionArray value={value} depth={depth} />;
  const object = asObject(value);
  if (object !== null) return <ProjectionObject value={object} depth={depth} />;
  if (typeof value === 'string') {
    return <p className="whitespace-pre-wrap text-xs text-text-secondary">{value || '—'}</p>;
  }
  return <p className="text-xs text-text-secondary">{String(value)}</p>;
}

/** Full parsed projection result: meta line + section grid + claims + deps. */
export function ProjectionResultView({ result }: { result: ProjectionResultModel }) {
  return (
    <div className="flex flex-col gap-3">
      {(result.generatedAt || result.tenantId) && (
        <p className="break-all font-mono text-[11px] text-text-muted">
          {result.projectionId ? `${result.projectionId} · ` : ''}tenant {result.tenantId || '—'}
          {result.generatedAt ? ` · generated ${result.generatedAt}` : ''}
          {result.asOf ? ` · asOf ${result.asOf}` : ''}
        </p>
      )}
      {result.sections.length > 0 ? (
        <div className="grid grid-cols-1 items-start gap-3 xl:grid-cols-2">
          {result.sections.map(section => (
            <ProjectionSectionCard key={section.id} section={section} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-text-muted">No projection sections were returned for this subject.</p>
      )}
      <ProjectionClaimsList claims={result.claims} />
      <ProjectionDependencyList dependencies={result.dependencyState} />
      {result.degradedReasons.length > 0 && (
        <p className="text-[11px] text-text-muted">
          degraded: {result.degradedReasons.join('; ')}
        </p>
      )}
    </div>
  );
}

/** One projection section rendered as a card with an honest state badge. */
export function ProjectionSectionCard({ section }: { section: ProjectionSectionModel }) {
  const title = section.title ?? section.id;
  return (
    <Card className="h-full">
      <CardHeader>
        <div className="flex min-w-0 items-center gap-2">
          <CardTitle className="truncate">{title}</CardTitle>
          <span className="font-mono text-[10px] text-text-muted">{section.id}</span>
        </div>
        {stateBadge(section.state, sectionTone) ?? <Badge variant="default">—</Badge>}
      </CardHeader>
      <CardContent className="space-y-2">
        {section.warnings.length > 0 && (
          <div className="space-y-1 rounded border border-warning/30 bg-warning/10 p-2">
            {section.warnings.map(warning => (
              <p key={warning} className="text-[11px] leading-relaxed text-warning">{warning}</p>
            ))}
          </div>
        )}
        {sectionHasContent(section) ? (
          <ProjectionContent value={section.content} />
        ) : (
          <p className="text-xs text-text-muted">No content for this section.</p>
        )}
      </CardContent>
    </Card>
  );
}

/** Evidence-grounded claims the projection made about its subject. */
export function ProjectionClaimsList({ claims }: { claims: readonly ProjectionClaimModel[] }) {
  if (claims.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Claims</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {claims.map(claim => {
          const subject = claim.subjectKind ? `${claim.subjectKind}:${claim.subjectId}` : '';
          return (
            <div key={claim.id || `${claim.kind}-${claim.subjectId}`} className="rounded-md border border-border-subtle p-3">
              <div className="flex flex-wrap items-center gap-1.5">
                {claim.kind && <Badge variant="default">{claim.kind}</Badge>}
                {claim.id && <span className="font-mono text-[10px] text-text-muted">{claim.id}</span>}
                {claim.confidence !== null && (
                  <Badge variant="info">confidence {claim.confidence}</Badge>
                )}
              </div>
              {claim.claims.length > 0 && (
                <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-xs text-text-secondary">
                  {claim.claims.map(text => (
                    <li key={text}>{text}</li>
                  ))}
                </ul>
              )}
              <p className="mt-1.5 text-[10px] text-text-muted">
                {subject && <span className="font-mono">{subject}</span>}
                {subject && ' · '}evidence refs {claim.evidenceRefCount}
              </p>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

/** Sibling-projection dependency state echoed from the projection result. */
export function ProjectionDependencyList({ dependencies }: { dependencies: readonly ProjectionDependencyModel[] }) {
  if (dependencies.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Dependency state</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap items-center gap-2">
          {dependencies.map(dep => (
            <span key={dep.projectionId} className="inline-flex items-center gap-1.5">
              <span className="font-mono text-[11px] text-text-secondary">{dep.projectionId}</span>
              {stateBadge(dep.state, sectionTone)}
              {dep.reason !== null && (
                <span className="text-[10px] text-text-muted">{dep.reason}</span>
              )}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

interface PlaneHealthBadgeProps {
  readonly name: string;
  readonly health: unknown;
  readonly isLoading: boolean;
}

/**
 * Plane probe summary for a read-only projection surface. The plane health route
 * resolves to `null` when the routes are not mounted (flag OFF) — rendered as an
 * honest "not enabled" state, never as an error. When reachable, the probe echoes
 * the registry availability ({registered, registryState, contractCompatible}).
 */
export function ProjectionPlaneHealth({ name, health, isLoading }: PlaneHealthBadgeProps) {
  const record = asObject(health);
  const availability = asObject(record?.availability);

  if (isLoading) {
    return <Badge variant="info">probing {name} plane…</Badge>;
  }
  if (record === null) {
    return (
      <Badge variant="default">
        {name} plane not enabled on this backend
      </Badge>
    );
  }

  const projectionId = typeof record.projectionId === 'string' ? record.projectionId : null;
  const registered = availability ? availability.registered : undefined;
  const compatible = availability ? availability.contractCompatible : undefined;
  const registryState = availability
    ? displayText(availability.registryState, '—')
    : null;
  const capabilityCount = Array.isArray(record.capabilityKeys) ? record.capabilityKeys.length : 0;

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {projectionId && (
        <Badge variant="success">{projectionId} plane enabled</Badge>
      )}
      {registryState && <Badge variant="default">{registryState}</Badge>}
      {typeof registered === 'boolean' && (
        <Badge variant={registered ? 'success' : 'warning'}>
          {registered ? 'provider registered' : 'provider not registered'}
        </Badge>
      )}
      {typeof compatible === 'boolean' && (
        <Badge variant={compatible ? 'default' : 'warning'}>
          {compatible ? 'contract-compatible' : 'contract mismatch'}
        </Badge>
      )}
      {capabilityCount > 0 && (
        <span className="font-mono text-[10px] text-text-muted">{capabilityCount} caps</span>
      )}
    </span>
  );
}

interface ProjectionSubjectPickerProps {
  readonly planeName: string;
  readonly kinds: readonly string[];
  readonly kind: string;
  readonly onKindChange: (kind: string) => void;
  readonly subjectId: string;
  readonly onSubjectIdChange: (subjectId: string) => void;
  readonly onRun: () => void;
  readonly onClear?: () => void;
}

/** Subject picker shared by the risk360 / fraud360 operator surfaces. */
export function ProjectionSubjectPicker({
  planeName,
  kinds,
  kind,
  onKindChange,
  subjectId,
  onSubjectIdChange,
  onRun,
  onClear,
}: ProjectionSubjectPickerProps) {
  return (
    <Card>
      <CardContent>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-text-muted">
            Subject kind
            <select
              value={kind}
              onChange={e => onKindChange(e.target.value)}
              className="border border-border-default rounded px-2 py-1.5 text-sm bg-surface-raised text-text-primary"
            >
              {kinds.map(option => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </label>
          <label className="flex min-w-56 flex-1 flex-col gap-1 text-xs text-text-muted">
            Subject ID
            <input
              value={subjectId}
              onChange={e => onSubjectIdChange(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && subjectId.trim()) onRun(); }}
              placeholder="e.g. entity_uuid"
              spellCheck={false}
              className="w-full border border-border-default rounded px-2 py-1.5 text-sm font-mono bg-surface-raised text-text-primary"
            />
          </label>
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={onRun} disabled={!subjectId.trim()}>
              Run {planeName} projection
            </Button>
            {onClear && (
              <Button variant="ghost" size="sm" onClick={onClear}>
                Clear
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
