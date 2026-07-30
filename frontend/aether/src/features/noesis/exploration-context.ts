import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';

export const NOESIS_EXPLORATION_CONTEXT_FILTER = 'exploration_context_v1';

export interface NoesisRequestContext {
  readonly current_page?: string;
  readonly selected_entity_id?: string;
  readonly selected_entity_type?: string;
  readonly time_range?: string;
  readonly filters: Record<string, unknown>;
}

/**
 * Carry the canonical exploration context without pretending Noesis' narrower
 * native fields can express it. The authenticated backend remains the tenant
 * authority; tenant_id is never promoted to request authority.
 */
export function buildNoesisRequestContext(
  exploration: ExplorationContextV1,
  currentPage: string,
): NoesisRequestContext {
  const focused = exploration.selection?.focused ?? null;
  const explicitlySelected = exploration.selection?.selected ?? [];
  const singleSubject = focused ?? (explicitlySelected.length === 1 ? explicitlySelected[0] : undefined);

  return {
    current_page: currentPage,
    ...(singleSubject
      ? {
          selected_entity_id: singleSubject.id,
          selected_entity_type: singleSubject.kind,
        }
      : {}),
    filters: {
      [NOESIS_EXPLORATION_CONTEXT_FILTER]: exploration,
    },
  };
}

export function exactContextHandoffLimitations(exploration: ExplorationContextV1): {
  readonly investigation: string;
  readonly export: string;
} {
  const selectedCount = exploration.selection?.selected?.length ?? 0;
  return {
    investigation:
      selectedCount === 0
        ? 'Select explicit subjects first. All-matching handoff requires a backend selection token.'
        : 'Unavailable: the investigation API can retain subjects, but not this exact time, cohort, query, and evidence context.',
    export:
      'Unavailable: analytics export cannot accept the canonical exploration query without dropping context.',
  };
}
