/**
 * URL codec for `ExplorationContextV1` — the URL is the authoritative,
 * shareable exploration state.
 *
 * Safety invariant: the encoded query string carries ONLY registry field
 * names, registry-constrained operators, and opaque ids / enum codes / numbers
 * / ISO instants. Filter expressions are sanitised against the canonical
 * `filterFields` registry before encoding — any unknown field, or an operator
 * a field did not register, is dropped. The registry contains no `pii`-class
 * field, so no personally identifying free text can reach a URL.
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
  TruthRequirements,
} from '@aether/shared';
import type {
  DimensionState,
  FilterExpression,
  FilterGroup,
  FilterOperator,
  RelationshipLayer,
  TemporalAuthority,
  TemporalRange,
} from '@aether/shared';

import {
  isKnownField,
  isKnownSurface,
  isOperatorValidForField,
  isValuelessOperator,
} from './registry';

const enc = encodeURIComponent;
const dec = decodeURIComponent;

// ── FilterGroup sanitisation (registry-only guarantee) ───────────────────────

function isGroup(node: FilterExpression | FilterGroup): node is FilterGroup {
  return (node as FilterGroup).logic !== undefined;
}

/**
 * Drop any expression whose field is not in the registry or whose operator the
 * field did not register; recurse into nested groups; drop groups left empty.
 * Returns null when nothing survives.
 */
export function sanitizeFilterGroup(group: FilterGroup): FilterGroup | null {
  const kept: Array<FilterExpression | FilterGroup> = [];
  for (const node of group.expressions) {
    if (isGroup(node)) {
      const nested = sanitizeFilterGroup(node);
      if (nested) kept.push(nested);
    } else if (isKnownField(node.field) && isOperatorValidForField(node.field, node.op)) {
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
    else if (ch === '}') depth -= 1;
    else if (ch === '|' && depth === 0) {
      parts.push(body.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(body.slice(start));
  return parts.filter((p) => p.length > 0);
}

const GROUP_HEAD = /^(AND|OR|NOT)\{/;

function parseNode(token: string): FilterExpression | FilterGroup | null {
  const head = GROUP_HEAD.exec(token);
  if (head && token.endsWith('}')) {
    const logic = head[1] as FilterGroup['logic'];
    const inner = token.slice(head[0].length, -1);
    const expressions = splitTopLevel(inner)
      .map(parseNode)
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
    return { field, op, value: null };
  }
  let value: unknown = null;
  try {
    value = JSON.parse(dec(rest.slice(second + 1)));
  } catch {
    return null;
  }
  return { field, op, value };
}

export function encodeFilterGroup(group: FilterGroup): string {
  return encodeGroupGrammar(group);
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
  return { kind: dec(token.slice(0, idx)), id: dec(token.slice(idx + 1)) };
}

function csv(values: readonly string[]): string {
  return values.map(enc).join(',');
}

function decsv(raw: string): string[] {
  return raw.split(',').filter((s) => s.length > 0).map(dec);
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

  p.set('surface', ctx.scope.surface);

  if (ctx.anchors?.length) p.set('anchors', ctx.anchors.map(encodeAnchor).join(','));

  if (ctx.population) {
    const clean = sanitizeFilterGroup(ctx.population);
    if (clean) p.set('pop', encodeFilterGroup(clean));
  }

  const t = ctx.temporal;
  p.set('tmode', t.mode);
  p.set('tfield', t.field);
  p.set('tz', t.timezone);
  if (t.authority) p.set('tauth', t.authority);
  if (t.as_of) p.set('tas', t.as_of);
  if (t.compare_to) p.set('tcmp', t.compare_to);
  if (t.range) p.set('trange', enc(JSON.stringify(t.range)));

  const g = ctx.graph;
  if (g) {
    if (g.layers?.length) p.set('glayers', csv(g.layers));
    if (g.edge_types?.length) p.set('gedges', csv(g.edge_types));
    if (g.direction) p.set('gdir', g.direction);
    if (g.depth != null) p.set('gdepth', String(g.depth));
    if (g.traversal_mode) p.set('gmode', g.traversal_mode);
    if (g.k != null) p.set('gk', String(g.k));
  }

  if (ctx.dimensions?.length) p.set('dims', csv(ctx.dimensions));
  if (ctx.overlays?.length) p.set('overlays', csv(ctx.overlays));

  const pr = ctx.presentation;
  if (pr) {
    p.set('pview', pr.view);
    if (pr.group_by?.length) p.set('pgroup', csv(pr.group_by));
    if (pr.columns?.length) p.set('pcols', csv(pr.columns));
    if (pr.page_size != null) p.set('pps', String(pr.page_size));
    if (pr.sort?.length) {
      p.set('psort', pr.sort.map((s) => `${enc(s.field)}~${s.direction === 'desc' ? 'd' : 'a'}`).join(','));
    }
  }

  const sel = ctx.selection;
  if (sel?.focused) p.set('focus', encodeAnchor(sel.focused));
  if (sel?.selected?.length) p.set('sel', sel.selected.map(encodeAnchor).join(','));

  const tr = ctx.truth;
  if (tr) {
    if (tr.minimum_confidence != null) p.set('tconf', String(tr.minimum_confidence));
    if (tr.allowed_dimension_states?.length) p.set('tstates', csv(tr.allowed_dimension_states));
    if (tr.include_evidence) p.set('tev', '1');
    if (tr.include_provenance) p.set('tprov', '1');
  }

  return p.toString();
}

/** Decode a query string back into an exploration context. */
export function decodeExplorationContext(
  query: string,
  defaults: DecodeDefaults,
): ExplorationContextV1 {
  const p = new URLSearchParams(query.startsWith('?') ? query.slice(1) : query);

  const surface = p.get('surface') ?? defaults.surface ?? '';

  const temporal: TemporalSelection = {
    mode: (p.get('tmode') ?? 'window') as ExplorationTemporalMode,
    field: (p.get('tfield') ?? 'occurred_at') as ExplorationTemporalField,
    timezone: p.get('tz') ?? 'UTC',
  };
  const tauth = p.get('tauth');
  if (tauth) temporal.authority = tauth as TemporalAuthority;
  const tas = p.get('tas');
  if (tas) temporal.as_of = tas;
  const tcmp = p.get('tcmp');
  if (tcmp) temporal.compare_to = tcmp;
  const trange = p.get('trange');
  if (trange) {
    try {
      temporal.range = JSON.parse(dec(trange)) as TemporalRange;
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
    const parsed = anchors.split(',').map(decodeAnchor).filter((a): a is ExplorationAnchor => a !== null);
    if (parsed.length) ctx.anchors = parsed;
  }

  const pop = p.get('pop');
  if (pop) {
    const group = decodeFilterGroup(pop);
    if (group) ctx.population = group;
  }

  const graph: GraphConstraints = {};
  const glayers = p.get('glayers');
  if (glayers) graph.layers = decsv(glayers) as RelationshipLayer[];
  const gedges = p.get('gedges');
  if (gedges) graph.edge_types = decsv(gedges);
  const gdir = p.get('gdir');
  if (gdir === 'in' || gdir === 'out' || gdir === 'both') graph.direction = gdir;
  const gdepth = p.get('gdepth');
  if (gdepth != null && gdepth !== '') graph.depth = Number(gdepth);
  const gmode = p.get('gmode');
  if (gmode === 'shortest' || gmode === 'strongest' || gmode === 'k_shortest') graph.traversal_mode = gmode;
  const gk = p.get('gk');
  if (gk != null && gk !== '') graph.k = Number(gk);
  if (Object.keys(graph).length) ctx.graph = graph;

  const dims = p.get('dims');
  if (dims) ctx.dimensions = decsv(dims);
  const overlays = p.get('overlays');
  if (overlays) ctx.overlays = decsv(overlays);

  const pview = p.get('pview');
  if (pview) {
    const presentation: PresentationSpec = { view: pview as ExplorationView };
    const pgroup = p.get('pgroup');
    if (pgroup) presentation.group_by = decsv(pgroup);
    const pcols = p.get('pcols');
    if (pcols) presentation.columns = decsv(pcols);
    const pps = p.get('pps');
    if (pps != null && pps !== '') presentation.page_size = Number(pps);
    const psort = p.get('psort');
    if (psort) {
      const sort: ExplorationSort[] = psort
        .split(',')
        .filter((s) => s.length > 0)
        .map((token) => {
          const idx = token.lastIndexOf('~');
          const field = idx < 0 ? token : token.slice(0, idx);
          const dir = idx < 0 ? 'a' : token.slice(idx + 1);
          return { field: dec(field), direction: dir === 'd' ? 'desc' : 'asc' };
        });
      if (sort.length) presentation.sort = sort;
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
    const parsed = sel.split(',').map(decodeAnchor).filter((a): a is ExplorationAnchor => a !== null);
    if (parsed.length) selection.selected = parsed;
  }
  if (selection.focused || selection.selected) ctx.selection = selection;

  const truth: TruthRequirements = {};
  const tconf = p.get('tconf');
  if (tconf != null && tconf !== '') truth.minimum_confidence = Number(tconf);
  const tstates = p.get('tstates');
  if (tstates) truth.allowed_dimension_states = decsv(tstates) as DimensionState[];
  if (p.get('tev') === '1') truth.include_evidence = true;
  if (p.get('tprov') === '1') truth.include_provenance = true;
  if (Object.keys(truth).length) ctx.truth = truth;

  return ctx;
}

/** Whether a decoded surface is one the fabric registers (for honest fallbacks). */
export function decodedSurfaceIsKnown(ctx: ExplorationContextV1): boolean {
  return isKnownSurface(ctx.scope.surface);
}
