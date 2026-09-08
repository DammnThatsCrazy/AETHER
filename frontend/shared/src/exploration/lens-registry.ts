/**
 * Phase 1 exploration lens runtime.
 *
 * The projection and engine lens registries in @aether/shared remain the
 * authority.  This module is only the small, frontend-facing join between
 * those registries and the existing exploration surface capabilities.  In
 * particular, a blueprint family that does not have a canonical engine lens
 * is represented as pending; it is never given a made-up projection id.
 */

import {
  explorationSurfaceIds,
  surfaceCapabilities,
  type ExplorationSurfaceId,
  type FilterFieldCategory,
  type IntelligenceProjectionDefinition,
  type IntelligenceProjectionId,
  type IntelligenceProjectionSubjectKind,
  intelligenceProjectionDefinitions,
} from '@aether/shared';
import {
  lensDefinitions,
  type LensDescriptor,
  type LensId,
} from '@aether/shared/lenses_generated';
import {
  resolveCapabilityState as resolveActionCapabilityState,
  type ActionCapabilityEvaluation,
  type CapabilityAvailability,
} from '@aether/shared/action-runtime-contract';

/** Blueprint vocabulary, deliberately distinct from canonical engine LensId. */
export const blueprintLensIds = [
  'object',
  'relationship',
  'evidence',
  'signals',
  'value',
  'syndicates',
  'geography',
  'time',
  'confidence',
  'freshness',
  'domain',
] as const;

export type BlueprintLensId = (typeof blueprintLensIds)[number];
export type LensAvailability = CapabilityAvailability;

type SurfaceCategory = FilterFieldCategory;

/** A capability value supplied by the already-authenticated runtime. */
export type LensCapabilityInput =
  | boolean
  | Pick<ActionCapabilityEvaluation, 'entitled' | 'permitted' | 'ready' | 'evidence_refs'>;

/** Runtime facts used for a pure, deterministic lens resolution. */
export interface LensResolutionContext {
  readonly objectKind: string;
  readonly surfaceId: string;
  /** Either compact booleans or the canonical action capability evaluation. */
  readonly capabilities?: Readonly<Record<string, LensCapabilityInput>>;
  /** Existing capability payloads can be passed directly; feature flags are used as capabilities. */
  readonly featureFlags?: Readonly<Record<string, boolean>>;
  readonly permissions?: Readonly<Record<string, boolean>>;
  /** Readiness is a fact from the caller, never inferred from a registry row. */
  readonly readiness?: Readonly<Record<string, boolean>>;
  /** Other selected blueprint families, used only for incompatibility checks. */
  readonly activeLensIds?: readonly string[];
}

export interface LensRegistryEntry {
  readonly id: BlueprintLensId;
  readonly displayName: string;
  readonly description: string;
  /** Canonical engine lens, when the blueprint family has one. */
  readonly canonicalLensId: LensId | null;
  readonly projectionIds: readonly IntelligenceProjectionId[];
  readonly supportedObjectKinds: readonly IntelligenceProjectionSubjectKind[];
  readonly supportedSurfaceIds: readonly ExplorationSurfaceId[];
  readonly supportedFieldCategories: readonly SurfaceCategory[];
  readonly requiredPermissions: readonly string[];
  readonly requiredCapabilities: readonly string[];
  readonly incompatibleWith: readonly BlueprintLensId[];
  /** True means the family has no canonical engine binding yet. */
  readonly pending: boolean;
}

export interface LensResolution {
  readonly lensId: string;
  readonly availability: LensAvailability;
  readonly reasons: readonly string[];
  readonly entry?: LensRegistryEntry;
}

export interface LensSetResolution {
  readonly availability: LensAvailability;
  readonly resolutions: readonly LensResolution[];
  readonly incompatiblePairs: readonly (readonly [BlueprintLensId, BlueprintLensId])[];
}

interface LensBinding {
  readonly canonicalLensId: LensId | null;
  readonly projectionIds: readonly IntelligenceProjectionId[];
  readonly supportedFieldCategories: readonly SurfaceCategory[];
  readonly requiredPermissions?: readonly string[];
  readonly requiredCapabilities?: readonly string[];
  readonly incompatibleWith?: readonly BlueprintLensId[];
  readonly pending?: boolean;
}

/*
 * These are joins, not a second projection registry.  Names absent from the
 * generated engine registry intentionally have no projection binding.
 */
const BLUEPRINT_BINDINGS: Record<BlueprintLensId, LensBinding> = {
  object: {
    canonicalLensId: 'standard',
    projectionIds: ['profile360'],
    supportedFieldCategories: ['entity'],
    incompatibleWith: ['syndicates'],
  },
  relationship: {
    canonicalLensId: 'relationship',
    projectionIds: ['relationship360'],
    supportedFieldCategories: ['graph'],
  },
  evidence: {
    canonicalLensId: 'evidence',
    projectionIds: [],
    supportedFieldCategories: ['truth'],
  },
  signals: {
    canonicalLensId: null,
    projectionIds: [],
    supportedFieldCategories: ['social', 'source', 'evidence'],
    pending: true,
  },
  value: {
    canonicalLensId: 'economic',
    projectionIds: ['economic360'],
    supportedFieldCategories: ['economic'],
  },
  syndicates: {
    canonicalLensId: null,
    projectionIds: [],
    supportedFieldCategories: ['graph'],
    pending: true,
  },
  geography: {
    canonicalLensId: 'geographic',
    projectionIds: ['geographic360'],
    supportedFieldCategories: ['geography'],
  },
  time: {
    canonicalLensId: 'temporal',
    projectionIds: ['temporal360'],
    supportedFieldCategories: ['time'],
  },
  confidence: {
    canonicalLensId: null,
    projectionIds: [],
    supportedFieldCategories: ['risk', 'truth'],
    pending: true,
  },
  freshness: {
    canonicalLensId: 'data_quality',
    projectionIds: [],
    supportedFieldCategories: ['truth', 'time'],
  },
  domain: {
    canonicalLensId: null,
    projectionIds: [],
    supportedFieldCategories: [],
    pending: true,
  },
};

const asReadonlySet = (values: readonly string[]): ReadonlySet<string> => new Set(values);

const SUBJECT_KINDS: readonly IntelligenceProjectionSubjectKind[] = [
  'agent',
  'campaign',
  'cluster',
  'connection',
  'deployment',
  'entity',
  'episode',
  'infrastructure',
  'population',
  'relationship',
  'source',
];

function projectionSurfaceIds(projections: readonly IntelligenceProjectionDefinition[]): ExplorationSurfaceId[] {
  const ids = new Set<ExplorationSurfaceId>();
  for (const projection of projections) {
    for (const surfaceId of projection.surfaceIds) {
      if (surfaceId in surfaceCapabilities) ids.add(surfaceId as ExplorationSurfaceId);
    }
  }
  return explorationSurfaceIds.filter((surfaceId) => ids.has(surfaceId));
}

function projectionObjectKinds(
  projections: readonly IntelligenceProjectionDefinition[],
): IntelligenceProjectionSubjectKind[] {
  const kinds = new Set<IntelligenceProjectionSubjectKind>();
  for (const projection of projections) {
    for (const kind of projection.subjectKinds) kinds.add(kind);
  }
  return SUBJECT_KINDS.filter((kind) => kinds.has(kind));
}

function descriptorFor(canonicalLensId: LensId | null): LensDescriptor | null {
  return canonicalLensId ? lensDefinitions[canonicalLensId] ?? null : null;
}

function projectionFor(id: IntelligenceProjectionId): IntelligenceProjectionDefinition {
  return intelligenceProjectionDefinitions[id];
}

function unionRequiredCapabilities(
  projections: readonly IntelligenceProjectionDefinition[],
  suffix: string,
): string[] {
  const values = new Set<string>();
  for (const projection of projections) {
    for (const key of projection.capabilityKeys) {
      if (key.endsWith(suffix)) values.add(key);
    }
  }
  return [...values].sort();
}

function buildEntry(id: BlueprintLensId): LensRegistryEntry {
  const binding = BLUEPRINT_BINDINGS[id];
  const projections = binding.projectionIds.map(projectionFor);
  const descriptor = descriptorFor(binding.canonicalLensId);
  const objectKinds = projections.length
    ? projectionObjectKinds(projections)
    : descriptor?.applicableSubjectKinds.filter((kind): kind is IntelligenceProjectionSubjectKind =>
        SUBJECT_KINDS.includes(kind as IntelligenceProjectionSubjectKind),
      ) ?? [];
  const surfaces = projections.length
    ? projectionSurfaceIds(projections)
    : explorationSurfaceIds.filter((surfaceId) => {
        const categories = asReadonlySet(surfaceCapabilities[surfaceId].supportedFieldCategories);
        return binding.supportedFieldCategories.length === 0 || binding.supportedFieldCategories.some((category) => categories.has(category));
      });
  return {
    id,
    displayName: descriptor?.displayName ?? id[0]!.toUpperCase() + id.slice(1),
    description: descriptor?.description ?? `The ${id} blueprint lens is pending a canonical engine binding.`,
    canonicalLensId: binding.canonicalLensId,
    projectionIds: binding.projectionIds,
    supportedObjectKinds: objectKinds,
    supportedSurfaceIds: surfaces,
    supportedFieldCategories: binding.supportedFieldCategories,
    requiredPermissions: binding.requiredPermissions ?? unionRequiredCapabilities(projections, '.read'),
    requiredCapabilities: binding.requiredCapabilities ?? unionRequiredCapabilities(projections, '.explore'),
    incompatibleWith: binding.incompatibleWith ?? [],
    pending: binding.pending ?? false,
  };
}

/** The complete Phase 1 family registry, stable in blueprint order. */
export const blueprintLensRegistry: Readonly<Record<BlueprintLensId, LensRegistryEntry>> = Object.fromEntries(
  blueprintLensIds.map((id) => [id, buildEntry(id)]),
) as Readonly<Record<BlueprintLensId, LensRegistryEntry>>;

export function allBlueprintLenses(): readonly LensRegistryEntry[] {
  return blueprintLensIds.map((id) => blueprintLensRegistry[id]);
}

export function getBlueprintLens(id: string): LensRegistryEntry | undefined {
  return blueprintLensRegistry[id as BlueprintLensId];
}

export function isKnownBlueprintLens(id: string): id is BlueprintLensId {
  return (blueprintLensIds as readonly string[]).includes(id);
}

export function lensSupportsObject(lensId: string, objectKind: string): boolean {
  return getBlueprintLens(lensId)?.supportedObjectKinds.includes(objectKind as IntelligenceProjectionSubjectKind) ?? false;
}

export function lensSupportsSurface(lensId: string, surfaceId: string): boolean {
  const entry = getBlueprintLens(lensId);
  if (!entry || !entry.supportedSurfaceIds.includes(surfaceId as ExplorationSurfaceId)) return false;
  if (entry.supportedFieldCategories.length === 0) return true;
  const surface = surfaceCapabilities[surfaceId as ExplorationSurfaceId];
  return entry.supportedFieldCategories.some((category) => surface?.supportedFieldCategories.includes(category));
}

function capabilityInput(
  context: LensResolutionContext,
  key: string,
): LensCapabilityInput | undefined {
  return context.capabilities?.[key] ?? context.featureFlags?.[key];
}

function capabilityAvailability(
  context: LensResolutionContext,
  key: string,
): LensAvailability {
  const input = capabilityInput(context, key);
  if (input === undefined) return 'not_ready';
  if (typeof input === 'boolean') {
    if (!input) return 'not_entitled';
    if (context.readiness?.[key] !== undefined) {
      return context.readiness[key] === true ? 'available' : 'not_ready';
    }
    return 'available';
  }
  // Preserve the canonical action-capability precedence when the caller has
  // supplied a full evaluation, including its evidence requirement.
  return resolveActionCapabilityState(input);
}

function worstAvailability(states: readonly LensAvailability[]): LensAvailability {
  if (states.includes('not_entitled')) return 'not_entitled';
  if (states.includes('unauthorized')) return 'unauthorized';
  if (states.includes('not_ready')) return 'not_ready';
  return 'available';
}

function pairKey(a: BlueprintLensId, b: BlueprintLensId): string {
  return [a, b].sort().join('::');
}

function incompatiblePairs(ids: readonly string[]): (readonly [BlueprintLensId, BlueprintLensId])[] {
  const known = ids.filter(isKnownBlueprintLens);
  const seen = new Set<string>();
  const pairs: (readonly [BlueprintLensId, BlueprintLensId])[] = [];
  for (const id of known) {
    const entry = blueprintLensRegistry[id];
    for (const other of entry.incompatibleWith) {
      if (known.includes(other) && id !== other && !seen.has(pairKey(id, other))) {
        seen.add(pairKey(id, other));
        pairs.push([id, other]);
      }
    }
  }
  return pairs;
}

/** Resolve one family without consulting network state or inventing readiness. */
export function resolveLensAvailability(
  lensId: string,
  context: LensResolutionContext,
): LensResolution {
  const entry = getBlueprintLens(lensId);
  if (!entry) return { lensId, availability: 'not_ready', reasons: ['lens_not_registered'] };
  const reasons: string[] = [];
  const states: LensAvailability[] = [];
  if (!lensSupportsObject(lensId, context.objectKind)) {
    states.push('not_ready');
    reasons.push('object_kind_not_supported');
  }
  if (!lensSupportsSurface(lensId, context.surfaceId)) {
    states.push('not_ready');
    reasons.push('surface_not_supported');
  }
  if (entry.pending) {
    states.push('not_ready');
    reasons.push('canonical_lens_pending');
  }
  for (const key of entry.requiredCapabilities) {
    const state = capabilityAvailability(context, key);
    states.push(state);
    if (state !== 'available') reasons.push(`capability:${key}:${state}`);
  }
  for (const key of entry.requiredPermissions) {
    const state = context.permissions?.[key] === true ? 'available' : 'unauthorized';
    states.push(state);
    if (state !== 'available') reasons.push(`permission:${key}:${state}`);
  }
  for (const [left, right] of incompatiblePairs(context.activeLensIds ?? [])) {
    if (left === lensId || right === lensId) {
      states.push('not_ready');
      reasons.push(`incompatible_lens:${left}:${right}`);
    }
  }
  return { lensId, availability: worstAvailability(states), reasons, entry };
}

/** Resolve an ordered set and report conflicts symmetrically and deterministically. */
export function resolveLensSetAvailability(
  lensIds: readonly string[],
  context: Omit<LensResolutionContext, 'activeLensIds'>,
): LensSetResolution {
  const activeLensIds = [...lensIds];
  const incompatible = incompatiblePairs(activeLensIds);
  const resolutions = activeLensIds.map((lensId) =>
    resolveLensAvailability(lensId, { ...context, activeLensIds }),
  );
  return {
    availability: worstAvailability(resolutions.map((resolution) => resolution.availability)),
    resolutions,
    incompatiblePairs: incompatible,
  };
}

export const getLens = getBlueprintLens;
export const allLenses = allBlueprintLenses;
export const resolveLens = resolveLensAvailability;
export const resolveLensSet = resolveLensSetAvailability;
export const lensRegistry = blueprintLensRegistry;
export const phase1LensRegistry = blueprintLensRegistry;
export const getLensEntry = getBlueprintLens;
export const supportsObject = lensSupportsObject;
export const supportsSurface = lensSupportsSurface;
