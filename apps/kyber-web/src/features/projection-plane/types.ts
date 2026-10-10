/**
 * Local, deliberately-tolerant read model for the intelligence-projection
 * plane's ProjectionResult wire payload (risk360 / fraud360 operator surfaces).
 *
 * The backend returns `ProjectionResult.model_dump(mode="json")` — `sections` is
 * a LIST of `ProjectionSection`, each `{ id, state, title, content, warnings }`
 * (contracts in `shared/intelligence_projections/contracts.py`). Some gateways
 * may emit a `Record<id, section>` instead; the parsers accept both.
 *
 * A rendered surface must be tolerant: never trust `state`/`content` vocabulary
 * it has not seen, and never fabricate a section. These helpers only rely on the
 * stable envelope shape and pass unknown fields through untouched. `content` may
 * be a string, a structured object, an array, or null — consumers decide how to
 * render it.
 */

export interface ProjectionSectionModel {
  readonly id: string;
  readonly state: string | null;
  readonly title: string | null;
  readonly content: unknown;
  readonly warnings: readonly string[];
}

export interface ProjectionClaimModel {
  readonly id: string;
  readonly kind: string;
  readonly claims: readonly string[];
  readonly confidence: number | null;
  readonly evidenceRefCount: number;
  readonly subjectKind: string;
  readonly subjectId: string;
}

export interface ProjectionDependencyModel {
  readonly projectionId: string;
  readonly state: string;
  readonly reason: string | null;
}

export interface ProjectionResultModel {
  readonly projectionId: string;
  readonly tenantId: string;
  readonly generatedAt: string;
  readonly asOf: string | null;
  readonly sections: readonly ProjectionSectionModel[];
  readonly claims: readonly ProjectionClaimModel[];
  readonly dependencyState: readonly ProjectionDependencyModel[];
  readonly degradedReasons: readonly string[];
  /** The raw payload, kept for surfaces that want to render unschema'd detail. */
  readonly raw: Readonly<Record<string, unknown>> | null;
}

/** Canonical render order for the two 360 planes' section ids. */
const CANONICAL_SECTION_ORDER = ['summary', 'state', 'evidence', 'findings', 'health'] as const;

export type BadgeTone = 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

function asRecord(value: unknown): Readonly<Record<string, unknown>> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Readonly<Record<string, unknown>>)
    : null;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function warningList(value: unknown): readonly string[] {
  if (Array.isArray(value)) return value.filter((w): w is string => typeof w === 'string');
  if (typeof value === 'string' && value) return [value];
  return [];
}

function parseSections(sectionsRaw: unknown): readonly ProjectionSectionModel[] {
  const sections: ProjectionSectionModel[] = [];

  if (Array.isArray(sectionsRaw)) {
    for (const raw of sectionsRaw) {
      const record = asRecord(raw);
      const id = asString(record?.id);
      if (!record || !id) continue;
      sections.push({
        id,
        state: asString(record.state),
        title: asString(record.title),
        content: record.content ?? null,
        warnings: warningList(record.warnings),
      });
    }
  } else if (asRecord(sectionsRaw) !== null) {
    // Record keyed by section id -> section shape (defensive; the wire contract
    // ships a list, but a tolerant reader accepts the keyed form).
    for (const [key, raw] of Object.entries(asRecord(sectionsRaw) as Readonly<Record<string, unknown>>)) {
      const record = asRecord(raw);
      if (!record) continue;
      const id = asString(record.id) ?? key;
      sections.push({
        id,
        state: asString(record.state),
        title: asString(record.title),
        content: record.content ?? null,
        warnings: warningList(record.warnings),
      });
    }
  }

  // Stable render order: the canonical five first (when present), any extra /
  // unknown section ids appended after in server order.
  return sections
    .slice()
    .sort((a, b) => {
      const ia = CANONICAL_SECTION_ORDER.indexOf(a.id as (typeof CANONICAL_SECTION_ORDER)[number]);
      const ib = CANONICAL_SECTION_ORDER.indexOf(b.id as (typeof CANONICAL_SECTION_ORDER)[number]);
      if (ia !== -1 && ib !== -1) return ia - ib;
      if (ia !== -1) return -1;
      if (ib !== -1) return 1;
      return 0;
    });
}

function parseClaims(claimsRaw: unknown): readonly ProjectionClaimModel[] {
  if (!Array.isArray(claimsRaw)) return [];
  const claims: ProjectionClaimModel[] = [];
  for (const raw of claimsRaw) {
    const record = asRecord(raw);
    if (!record) continue;
    const subject = asRecord(record.subject);
    const evidence = Array.isArray(record.evidenceRefs) ? record.evidenceRefs : [];
    claims.push({
      id: asString(record.id) ?? '',
      kind: asString(record.kind) ?? '',
      claims: Array.isArray(record.claims) ? record.claims.filter((c): c is string => typeof c === 'string') : [],
      confidence: typeof record.confidence === 'number' ? record.confidence : null,
      evidenceRefCount: evidence.length,
      subjectKind: asString(subject?.kind) ?? '',
      subjectId: asString(subject?.id) ?? '',
    });
  }
  return claims;
}

function parseDependencyState(depsRaw: unknown): readonly ProjectionDependencyModel[] {
  if (!Array.isArray(depsRaw)) return [];
  const deps: ProjectionDependencyModel[] = [];
  for (const raw of depsRaw) {
    const record = asRecord(raw);
    if (!record) continue;
    const projectionId = asString(record.projectionId);
    const state = asString(record.state);
    if (!projectionId || !state) continue;
    deps.push({
      projectionId,
      state,
      reason: asString(record.reason),
    });
  }
  return deps;
}

/**
 * Parse an unknown projection payload into the tolerant read model. Returns
 * `null` when the payload is not a projection-shaped object.
 */
export function parseProjectionResult(payload: unknown): ProjectionResultModel | null {
  const record = asRecord(payload);
  if (!record) return null;
  return {
    projectionId: asString(record.projectionId) ?? '',
    tenantId: asString(record.tenantId) ?? '',
    generatedAt: asString(record.generatedAt) ?? '',
    asOf: asString(record.asOf),
    sections: parseSections(record.sections),
    claims: parseClaims(record.claims),
    dependencyState: parseDependencyState(record.dependencyState),
    degradedReasons: Array.isArray(record.degradedReasons)
      ? record.degradedReasons.filter((r): r is string => typeof r === 'string')
      : [],
    raw: record,
  };
}

/** A section whose content carries no renderable body (null/empty). */
export function sectionHasContent(section: ProjectionSectionModel): boolean {
  return section.content !== null && section.content !== undefined;
}

/**
 * True when an array item / content object looks like a material hypothesis or
 * finding candidate (fraud360 findings/state sections surface these as cards).
 */
export function isHypothesisLike(value: unknown): boolean {
  const record = asRecord(value);
  if (!record) return false;
  const hasId = typeof record.hypothesisId === 'string' || typeof record.id === 'string';
  const isCandidate = asString(record.state) !== null || asString(record.claimState) !== null;
  const hasHypothesisShape =
    'family' in record ||
    'matchedPatternIds' in record ||
    'materiality' in record ||
    'hypothesisId' in record ||
    'superseded_by_hypothesis_id' in record;
  return hasId && (isCandidate || hasHypothesisShape);
}

/** Honest badge tone for a projection SECTION state (available/degraded/...). */
export function sectionTone(state: unknown): BadgeTone {
  const s = String(state ?? '').toLowerCase();
  if (s === 'available' || s === 'ok' || s === 'ready' || s === 'reachable' || s === 'observed') return 'success';
  if (s === 'degraded' || s === 'stale' || s === 'partial') return 'warning';
  if (s === 'empty' || s === 'missing' || s === 'unknown' || s === 'not_applicable' || s === 'suppressed' || s === 'absent') {
    return 'default';
  }
  return 'info';
}

/** Honest badge tone for a fraud HYPOTHESIS state (candidate … confirmed). */
export function hypothesisTone(state: unknown): BadgeTone {
  const s = String(state ?? '').toLowerCase();
  if (s === 'confirmed') return 'danger';
  if (s === 'candidate' || s === 'under_evaluation' || s === 'inconclusive') return 'info';
  if (s === 'rejected' || s === 'closed' || s === 'superseded' || s === 'corrected') return 'default';
  // supported / material / investigating / disputed / stale + anything unknown:
  // never render stronger than the state the backend actually reports.
  return 'warning';
}

/** Text fallback used across the operator surfaces. */
export function displayText(value: unknown, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}
