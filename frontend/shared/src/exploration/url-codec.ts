/**
 * URL codec for `ExplorationContextV1` — the URL is the authoritative,
 * shareable exploration state.
 *
 * Safety invariant: the encoded query string carries ONLY registry field
 * names, registry-constrained operators, and opaque ids / enum codes / numbers
 * / ISO instants. Filter expressions are sanitised against the canonical
 * `filterFields` registry before encoding — any unknown field, or an operator
 * a field did not register, is dropped. Evidence and truth fields are not
 * shareable even when present in the filter registry.
 *
 * `tenant_id` is deliberately NOT encoded: it is session scope, not shareable
 * state, and is re-supplied at decode time.
 */

import type {
  ExplorationContextV1,
  ExplorationAnchor,
  ExplorationSort,
  ExplorationTemporalField,
  ExplorationTemporalMode,
  ExplorationView,
  GraphConstraints,
  PresentationSpec,
  SelectionSet,
  TemporalSelection,
} from '@aether/shared';
import type {
  FilterExpression,
  FilterGroup,
  FilterOperator,
  RelationshipLayer,
  TemporalAuthority,
  TemporalRange,
} from '@aether/shared';
import {
  explorationTemporalFields,
  explorationTemporalModes,
  explorationViews,
} from '@aether/shared/exploration-contract';
import { EDGE_LAYER_MAP, RELATIONSHIP_LAYERS } from '@aether/shared/graph-contract';
import { temporalAuthorities } from '@aether/shared/temporal';

import {
  getFilterField,
  isKnownField,
  isMultiValueOperator,
  isKnownSurface,
  isOperatorValidForField,
  isRangeOperator,
  isValuelessOperator,
} from './registry';

const enc = encodeURIComponent;
const dec = decodeURIComponent;

/** Defensive limits for a shareable URL (not a query execution budget). */
export const MAX_DEEP_LINK_LENGTH = 4096;
export const MAX_DEEP_LINK_ITEMS = 32;
export const MAX_DEEP_LINK_SELECTED = 64;
export const MAX_DEEP_LINK_FILTER_NODES = 64;
export const MAX_DEEP_LINK_FILTER_DEPTH = 8;
export const MAX_DEEP_LINK_TOKEN_LENGTH = 256;

const DEFAULT_TEMPORAL_MODE = 'window' as const;
const DEFAULT_TEMPORAL_FIELD = 'occurred_at' as const;
const DEFAULT_TIMEZONE = 'UTC';
const SAFE_FILTER_CATEGORIES = new Set([
  'campaign', 'device', 'economic', 'entity', 'geography', 'graph',
  'incentive', 'narrative', 'path', 'relationship', 'risk', 'social', 'source', 'time',
]);

function isSafeToken(value: unknown, max = MAX_DEEP_LINK_TOKEN_LENGTH): value is string {
  return typeof value === 'string'
    && value.length > 0
    && value.length <= max
    && !/[\u0000-\u001f\u007f]/.test(value);
}

function safeDecode(value: string): string | null {
  try {
    const decoded = dec(value);
    return isSafeToken(decoded) ? decoded : null;
  } catch {
    return null;
  }
}

function uniqueBounded<T>(values: readonly T[], max: number): T[] {
  return [...new Set(values)].slice(0, max);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isSafeInstant(value: unknown): value is string {
  return isSafeToken(value, 80)
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    && Number.isFinite(Date.parse(value));
}

function isSafeTimezone(value: unknown): value is string {
  if (!isSafeToken(value, 128) || value.includes('..') || value.startsWith('/')) return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: value }).format();
    return true;
  } catch {
    return false;
  }
}

function isValidRange(value: unknown): value is TemporalRange {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  if (candidate.kind === 'instant') {
    return Object.keys(candidate).every((key) => ['kind', 'start', 'endExclusive'].includes(key))
      && isSafeInstant(candidate.start) && isSafeInstant(candidate.endExclusive);
  }
  return candidate.kind === 'local_date'
    && Object.keys(candidate).every((key) => ['kind', 'startDate', 'endDateExclusive', 'timeZone'].includes(key))
    && typeof candidate.startDate === 'string'
    && /^\d{4}-\d{2}-\d{2}$/.test(candidate.startDate)
    && typeof candidate.endDateExclusive === 'string'
    && /^\d{4}-\d{2}-\d{2}$/.test(candidate.endDateExclusive)
    && isSafeTimezone(candidate.timeZone);
}

function isSafeFilterValue(field: string, op: FilterOperator, value: unknown): boolean {
  const definition = getFilterField(field);
  if (!definition || !SAFE_FILTER_CATEGORIES.has(definition.category)) return false;
  if (isValuelessOperator(op)) return true;

  const scalar = (candidate: unknown): boolean => {
    switch (definition.dataType) {
      case 'number': return isFiniteNumber(candidate) && Math.abs(candidate) <= Number.MAX_SAFE_INTEGER;
      case 'boolean': return typeof candidate === 'boolean';
      case 'datetime': return isSafeInstant(candidate);
      case 'string':
      case 'enum':
      case 'entity_ref':
      case 'geography':
        return isSafeToken(candidate);
      default: return false;
    }
  };

  if (isMultiValueOperator(op)) {
    return Array.isArray(value)
      && value.length > 0
      && value.length <= MAX_DEEP_LINK_ITEMS
      && value.every(scalar);
  }
  if (isRangeOperator(op)) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    const range = value as Record<string, unknown>;
    return Object.keys(range).every((key) => key === 'from' || key === 'to')
      && scalar(range.from)
      && scalar(range.to);
  }
  return scalar(value);
}

function isSafeFilterExpression(node: FilterExpression): boolean {
  return isKnownField(node.field)
    && isOperatorValidForField(node.field, node.op)
    && isSafeFilterValue(node.field, node.op, node.value);
}

// ── FilterGroup sanitisation (registry-only guarantee) ───────────────────────

function isGroup(node: FilterExpression | FilterGroup | null | undefined): node is FilterGroup {
  return Boolean(node && typeof node === 'object' && 'logic' in node && (node as FilterGroup).logic !== undefined);
}

/**
 * Drop any expression whose field is not in the registry or whose operator the
 * field did not register; recurse into nested groups; drop groups left empty.
 * Returns null when nothing survives.
 */
export function sanitizeFilterGroup(group: FilterGroup): FilterGroup | null {
  const budget = { nodes: 0 };
  return sanitizeFilterGroupBounded(group, budget, 0);
}

function sanitizeFilterGroupBounded(
  group: FilterGroup,
  budget: { nodes: number },
  depth: number,
): FilterGroup | null {
  if (!group || typeof group !== 'object'
    || (group.logic !== 'AND' && group.logic !== 'OR' && group.logic !== 'NOT')
    || depth > MAX_DEEP_LINK_FILTER_DEPTH
    || !Array.isArray(group.expressions)) return null;
  const kept: Array<FilterExpression | FilterGroup> = [];
  for (const node of group.expressions.slice(0, MAX_DEEP_LINK_FILTER_NODES)) {
    if (budget.nodes >= MAX_DEEP_LINK_FILTER_NODES) break;
    budget.nodes += 1;
    if (isGroup(node)) {
      const nested = sanitizeFilterGroupBounded(node, budget, depth + 1);
      if (nested) kept.push(nested);
    } else if (node && typeof node === 'object' && isSafeFilterExpression(node)) {
      kept.push(node);
    }
  }
  if (kept.length === 0) return null;
  return { logic: group.logic, expressions: kept };
}

// ── FilterGroup grammar ──────────────────────────────────────────────────────
// group ::= LOGIC '{' node ('|' node)* '}'
// node  ::= group | leaf
// leaf  ::= field ':' op [ ':' encodeURIComponent(JSON.stringify(value)) ]
// Structural delimiters are '{', '}', '|', ':'; every value atom is
// JSON-encoded then percent-encoded so it can never contain one.

function encodeLeaf(expr: FilterExpression): string {
  const head = `${expr.field}:${expr.op}`;
  if (isValuelessOperator(expr.op)) return head;
  return `${head}:${enc(JSON.stringify(expr.value ?? null))}`;
}

function encodeNode(node: FilterExpression | FilterGroup): string {
  if (isGroup(node)) return encodeGroupGrammar(node);
  return encodeLeaf(node);
}

function encodeGroupGrammar(group: FilterGroup): string {
  return `${group.logic}{${group.expressions.map(encodeNode).join('|')}}`;
}

/** Split a group body on top-level '|' (brace-depth aware). */
function splitTopLevel(body: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < body.length; i += 1) {
    const ch = body[i];
    if (ch === '{') depth += 1;
    else if (ch === '}') {
      depth -= 1;
      if (depth < 0) return [];
    }
    else if (ch === '|' && depth === 0) {
      parts.push(body.slice(start, i));
      start = i + 1;
    }
  }
  if (depth !== 0) return [];
  parts.push(body.slice(start));
  return parts.filter((p) => p.length > 0);
}

const GROUP_HEAD = /^(AND|OR|NOT)\{/;

function parseNode(
  token: string,
  budget: { nodes: number } = { nodes: 0 },
  depth = 0,
): FilterExpression | FilterGroup | null {
  if (token.length === 0 || token.length > MAX_DEEP_LINK_TOKEN_LENGTH * 8
    || depth > MAX_DEEP_LINK_FILTER_DEPTH || budget.nodes >= MAX_DEEP_LINK_FILTER_NODES) return null;
  budget.nodes += 1;
  const head = GROUP_HEAD.exec(token);
  if (head && token.endsWith('}')) {
    const logic = head[1] as FilterGroup['logic'];
    const inner = token.slice(head[0].length, -1);
    const expressions = splitTopLevel(inner)
      .map((child) => parseNode(child, budget, depth + 1))
      .filter((n): n is FilterExpression | FilterGroup => n !== null);
    if (expressions.length === 0) return null;
    return { logic, expressions };
  }
  // leaf: field ':' op [ ':' value ]
  const first = token.indexOf(':');
  if (first < 0) return null;
  const field = token.slice(0, first);
  const rest = token.slice(first + 1);
  const second = rest.indexOf(':');
  const op = (second < 0 ? rest : rest.slice(0, second)) as FilterOperator;
  if (!isKnownField(field) || !isOperatorValidForField(field, op)) return null;
  if (isValuelessOperator(op) || second < 0) {
    const expression = { field, op, value: null } as FilterExpression;
    return isSafeFilterExpression(expression) ? expression : null;
  }
  let value: unknown = null;
  try {
    value = JSON.parse(dec(rest.slice(second + 1)));
  } catch {
    return null;
  }
  const expression = { field, op, value } as FilterExpression;
  return isSafeFilterExpression(expression) ? expression : null;
}

export function encodeFilterGroup(group: FilterGroup): string {
  const clean = sanitizeFilterGroup(group);
  return clean ? encodeGroupGrammar(clean) : '';
}

export function decodeFilterGroup(raw: string): FilterGroup | null {
  const node = parseNode(raw);
  return node && isGroup(node) ? node : null;
}

// ── anchor / list helpers ────────────────────────────────────────────────────

function encodeAnchor(a: ExplorationAnchor): string {
  return `${enc(a.kind)}:${enc(a.id)}`;
}

function decodeAnchor(token: string): ExplorationAnchor | null {
  const idx = token.indexOf(':');
  if (idx < 0) return null;
  const kind = safeDecode(token.slice(0, idx));
  const id = safeDecode(token.slice(idx + 1));
  return kind && id ? { kind, id } : null;
}

function csv(values: readonly string[]): string {
  return values.map(enc).join(',');
}

function decsv(raw: string): string[] {
  return raw.split(',').filter((s) => s.length > 0)
    .map(safeDecode)
    .filter((s): s is string => s !== null);
}

function decodeAnchors(raw: string, max: number): ExplorationAnchor[] {
  const seen = new Set<string>();
  const result: ExplorationAnchor[] = [];
  for (const token of raw.split(',').slice(0, max)) {
    const anchor = decodeAnchor(token);
    if (!anchor) continue;
    const key = `${anchor.kind}\u0000${anchor.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(anchor);
  }
  return result;
}

function normalizeAnchors(values: readonly ExplorationAnchor[] | null | undefined, max: number): ExplorationAnchor[] {
  const result: ExplorationAnchor[] = [];
  const seen = new Set<string>();
  for (const value of values ?? []) {
    if (!isSafeToken(value?.kind) || !isSafeToken(value?.id)) continue;
    const key = `${value.kind}\u0000${value.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push({ kind: value.kind, id: value.id });
    if (result.length >= max) break;
  }
  return result;
}

function normalizeFields(values: readonly string[] | null | undefined): string[] {
  return uniqueBounded((values ?? []).filter((value) => isKnownField(value)), MAX_DEEP_LINK_ITEMS);
}

function validEnum<T extends string>(value: unknown, values: readonly T[]): value is T {
  return typeof value === 'string' && values.includes(value as T);
}

function validInteger(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;
}

function normalizeTemporal(temporal: ExplorationContextV1['temporal']): TemporalSelection {
  const result: TemporalSelection = {
    mode: validEnum(temporal?.mode, explorationTemporalModes) ? temporal.mode : DEFAULT_TEMPORAL_MODE,
    field: validEnum(temporal?.field, explorationTemporalFields) ? temporal.field : DEFAULT_TEMPORAL_FIELD,
    timezone: isSafeTimezone(temporal?.timezone) ? temporal.timezone : DEFAULT_TIMEZONE,
  };
  if (validEnum(temporal?.authority, temporalAuthorities)) result.authority = temporal.authority;
  if (isSafeInstant(temporal?.as_of)) result.as_of = temporal.as_of;
  if (isSafeInstant(temporal?.compare_to)) result.compare_to = temporal.compare_to;
  if (isValidRange(temporal?.range)) result.range = temporal.range;
  return result;
}

function normalizeGraph(graph: GraphConstraints | null | undefined): GraphConstraints {
  const result: GraphConstraints = {};
  const layers = uniqueBounded((graph?.layers ?? []).filter((layer): layer is RelationshipLayer => RELATIONSHIP_LAYERS.includes(layer)), RELATIONSHIP_LAYERS.length);
  const edgeTypes = uniqueBounded((graph?.edge_types ?? []).filter((edge) => typeof edge === 'string' && edge in EDGE_LAYER_MAP && isSafeToken(edge)), MAX_DEEP_LINK_ITEMS);
  if (layers.length) result.layers = layers;
  if (edgeTypes.length) result.edge_types = edgeTypes;
  if (validEnum(graph?.direction, ['in', 'out', 'both'] as const)) result.direction = graph.direction;
  if (validInteger(graph?.depth, 1, 6)) result.depth = graph.depth;
  if (validEnum(graph?.traversal_mode, ['shortest', 'strongest', 'k_shortest'] as const)) result.traversal_mode = graph.traversal_mode;
  if (validInteger(graph?.k, 1, 100)) result.k = graph.k;
  return result;
}

function normalizePresentation(presentation: PresentationSpec | null | undefined): PresentationSpec | null {
  if (!presentation || !validEnum(presentation.view, explorationViews)) return null;
  const result: PresentationSpec = { view: presentation.view };
  const groupBy = normalizeFields(presentation.group_by);
  const columns = normalizeFields(presentation.columns);
  if (groupBy.length) result.group_by = groupBy;
  if (columns.length) result.columns = columns;
  if (validInteger(presentation.page_size, 1, 500)) result.page_size = presentation.page_size;
  const sort = (presentation.sort ?? [])
    .filter((item) => item && isKnownField(item.field) && (item.direction === 'asc' || item.direction === 'desc'))
    .slice(0, MAX_DEEP_LINK_ITEMS)
    .map((item) => ({ field: item.field, direction: item.direction }));
  if (sort.length) result.sort = sort;
  return result;
}

function boundedQuery(p: URLSearchParams): string {
  if (p.toString().length <= MAX_DEEP_LINK_LENGTH) return p.toString();
  // Optional state is removed in descending order of privacy/size. The
  // remaining temporal/graph/presentation primitives are still useful and
  // remain bounded even for hostile input.
  for (const key of ['pop', 'sel', 'anchors', 'psort', 'pcols', 'pgroup', 'gedges', 'glayers', 'gmode', 'gk', 'trange', 'tas', 'tcmp']) {
    p.delete(key);
    if (p.toString().length <= MAX_DEEP_LINK_LENGTH) return p.toString();
  }
  return p.toString();
}

// ── top-level codec ──────────────────────────────────────────────────────────

export interface DecodeDefaults {
  /** Session tenant — never travels in the URL. */
  tenantId: string;
  /** Fallback surface when the query string omits it. */
  surface?: string;
}

/** Encode an exploration context to a query string (no leading '?'). */
export function encodeExplorationContext(ctx: ExplorationContextV1): string {
  const p = new URLSearchParams();

  const anchors = normalizeAnchors(ctx.anchors, MAX_DEEP_LINK_ITEMS);
  if (anchors.length) p.set('anchors', anchors.map(encodeAnchor).join(','));

  if (ctx.population) {
    const clean = sanitizeFilterGroup(ctx.population);
    if (clean) p.set('pop', encodeFilterGroup(clean));
  }

  const t = normalizeTemporal(ctx.temporal);
  p.set('tmode', t.mode);
  p.set('tfield', t.field);
  p.set('tz', t.timezone);
  if (t.authority) p.set('tauth', t.authority);
  if (t.as_of) p.set('tas', t.as_of);
  if (t.compare_to) p.set('tcmp', t.compare_to);
  if (t.range) p.set('trange', enc(JSON.stringify(t.range)));

  const g = normalizeGraph(ctx.graph);
  if (Object.keys(g).length) {
    if (g.layers?.length) p.set('glayers', csv(g.layers));
    if (g.edge_types?.length) p.set('gedges', csv(g.edge_types));
    if (g.direction) p.set('gdir', g.direction);
    if (g.depth != null) p.set('gdepth', String(g.depth));
    if (g.traversal_mode) p.set('gmode', g.traversal_mode);
    if (g.k != null) p.set('gk', String(g.k));
  }

  const pr = normalizePresentation(ctx.presentation);
  if (pr) {
    p.set('pview', pr.view);
    if (pr.group_by?.length) p.set('pgroup', csv(pr.group_by));
    if (pr.columns?.length) p.set('pcols', csv(pr.columns));
    if (pr.page_size != null) p.set('pps', String(pr.page_size));
    if (pr.sort?.length) {
      p.set('psort', pr.sort.map((s) => `${enc(s.field)}~${s.direction === 'desc' ? 'd' : 'a'}`).join(','));
    }
  }

  const focused = normalizeAnchors(ctx.selection?.focused ? [ctx.selection.focused] : [], 1)[0];
  const selected = normalizeAnchors(ctx.selection?.selected, MAX_DEEP_LINK_SELECTED);
  if (focused) p.set('focus', encodeAnchor(focused));
  if (selected.length) p.set('sel', selected.map(encodeAnchor).join(','));

  // Truth/evidence/rights/approval state is intentionally not URL-shareable.
  return boundedQuery(p);
}

/** Decode a query string back into an exploration context. */
export function decodeExplorationContext(
  query: string,
  defaults: DecodeDefaults,
): ExplorationContextV1 {
  const rawQuery = query.startsWith('?') ? query.slice(1) : query;
  const p = new URLSearchParams(rawQuery.length <= MAX_DEEP_LINK_LENGTH ? rawQuery : '');
  const surface = defaults.surface && isKnownSurface(defaults.surface) ? defaults.surface : '';

  const temporal: TemporalSelection = {
    mode: validEnum(p.get('tmode'), explorationTemporalModes) ? p.get('tmode') as ExplorationTemporalMode : DEFAULT_TEMPORAL_MODE,
    field: validEnum(p.get('tfield'), explorationTemporalFields) ? p.get('tfield') as ExplorationTemporalField : DEFAULT_TEMPORAL_FIELD,
    timezone: isSafeTimezone(p.get('tz')) ? p.get('tz') as string : DEFAULT_TIMEZONE,
  };
  const tauth = p.get('tauth');
  if (validEnum(tauth, temporalAuthorities)) temporal.authority = tauth as TemporalAuthority;
  const tas = p.get('tas');
  if (isSafeInstant(tas)) temporal.as_of = tas;
  const tcmp = p.get('tcmp');
  if (isSafeInstant(tcmp)) temporal.compare_to = tcmp;
  const trange = p.get('trange');
  if (trange) {
    try {
      const parsed = JSON.parse(dec(trange)) as unknown;
      if (isValidRange(parsed)) temporal.range = parsed;
    } catch {
      /* malformed range param — leave unset */
    }
  }

  const ctx: ExplorationContextV1 = {
    version: '1',
    scope: { tenant_id: defaults.tenantId, surface },
    temporal,
  };

  const anchors = p.get('anchors');
  if (anchors) {
    const parsed = decodeAnchors(anchors, MAX_DEEP_LINK_ITEMS);
    if (parsed.length) ctx.anchors = parsed;
  }

  const pop = p.get('pop');
  if (pop) {
    const group = decodeFilterGroup(pop);
    if (group) ctx.population = group;
  }

  const graph: GraphConstraints = {};
  const glayers = p.get('glayers');
  if (glayers) graph.layers = uniqueBounded(decsv(glayers)
    .filter((layer): layer is RelationshipLayer => RELATIONSHIP_LAYERS.includes(layer as RelationshipLayer)), RELATIONSHIP_LAYERS.length);
  const gedges = p.get('gedges');
  if (gedges) graph.edge_types = uniqueBounded(decsv(gedges)
    .filter((edge) => edge in EDGE_LAYER_MAP), MAX_DEEP_LINK_ITEMS);
  const gdir = p.get('gdir');
  if (validEnum(gdir, ['in', 'out', 'both'] as const)) graph.direction = gdir;
  const gdepth = p.get('gdepth');
  if (gdepth != null && gdepth !== '') {
    const depth = Number(gdepth);
    if (validInteger(depth, 1, 6)) graph.depth = depth;
  }
  const gmode = p.get('gmode');
  if (validEnum(gmode, ['shortest', 'strongest', 'k_shortest'] as const)) graph.traversal_mode = gmode;
  const gk = p.get('gk');
  if (gk != null && gk !== '') {
    const k = Number(gk);
    if (validInteger(k, 1, 100)) graph.k = k;
  }
  if (Object.keys(graph).length) ctx.graph = graph;

  const pview = p.get('pview');
  if (validEnum(pview, explorationViews)) {
    const presentation: PresentationSpec = { view: pview as ExplorationView };
    const pgroup = p.get('pgroup');
    if (pgroup) presentation.group_by = uniqueBounded(decsv(pgroup).filter(isKnownField), MAX_DEEP_LINK_ITEMS);
    const pcols = p.get('pcols');
    if (pcols) presentation.columns = uniqueBounded(decsv(pcols).filter(isKnownField), MAX_DEEP_LINK_ITEMS);
    const pps = p.get('pps');
    if (pps != null && pps !== '') {
      const pageSize = Number(pps);
      if (validInteger(pageSize, 1, 500)) presentation.page_size = pageSize;
    }
    const psort = p.get('psort');
    if (psort) {
      const sort = psort
        .split(',')
        .filter((s) => s.length > 0)
        .map((token) => {
          const idx = token.lastIndexOf('~');
          const field = idx < 0 ? token : token.slice(0, idx);
          const dir = idx < 0 ? 'a' : token.slice(idx + 1);
          const decodedField = safeDecode(field);
          return decodedField && isKnownField(decodedField) && (dir === 'a' || dir === 'd')
            ? { field: decodedField, direction: dir === 'd' ? 'desc' : 'asc' }
            : null;
        });
      const validSort = sort.filter((item): item is ExplorationSort => item !== null);
      if (validSort.length) presentation.sort = validSort.slice(0, MAX_DEEP_LINK_ITEMS);
    }
    ctx.presentation = presentation;
  }

  const selection: SelectionSet = {};
  const focus = p.get('focus');
  if (focus) {
    const a = decodeAnchor(focus);
    if (a) selection.focused = a;
  }
  const sel = p.get('sel');
  if (sel) {
    const parsed = decodeAnchors(sel, MAX_DEEP_LINK_SELECTED);
    if (parsed.length) selection.selected = parsed;
  }
  if (selection.focused || selection.selected) ctx.selection = selection;

  return ctx;
}

/** Whether a decoded surface is one the fabric registers (for honest fallbacks). */
export function decodedSurfaceIsKnown(ctx: ExplorationContextV1): boolean {
  return isKnownSurface(ctx.scope.surface);
}
