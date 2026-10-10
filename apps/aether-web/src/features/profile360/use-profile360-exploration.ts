import { useCallback, useEffect, useState } from 'react';
import { dimensionStates, type DimensionState } from '@aether/shared/dimension-state';
import type {
  ApplicabilityReport,
  ExplorationCompleteness,
  ExplorationContextV1,
  ExplorationResultEnvelope,
  ExplorationTruth,
} from '@aether/shared/exploration-contract';
import {
  useExplorationClient,
  useExplorationContext,
  type ExplorationStatus,
} from '@aether/ui/exploration';
import { RestClientError } from '@aether-app/lib/api/rest/client';

export interface ExplorationGraphNode {
  id: string;
  kind: string;
  label?: string | null;
  properties?: Record<string, unknown> | null;
}

export interface Profile360ExplorationData {
  anchor_id: string | null;
  entity: ExplorationGraphNode | null;
  related: ExplorationGraphNode[];
  edges: unknown[];
}

export interface Profile360ExplorationState {
  status: ExplorationStatus;
  data: Profile360ExplorationData | null;
  truth: ExplorationTruth | null;
  completeness: ExplorationCompleteness | null;
  applicability: ApplicabilityReport | null;
  error: string | null;
  refetch: () => void;
}

const CANONICAL_STATES = new Set<string>(dimensionStates);

/** Reject backend-local states before they reach the canonical truth renderer. */
export function assertCanonicalTruthState(state: string): asserts state is DimensionState {
  if (!CANONICAL_STATES.has(state)) {
    throw new Error(`Exploration contract violation: unknown truth state "${state}"`);
  }
}

export function profileContextFor(
  mounted: ExplorationContextV1,
  entityId: string,
): ExplorationContextV1 {
  const entityAnchor = { kind: 'entity', id: entityId };
  const anchors = [
    entityAnchor,
    ...(mounted.anchors ?? []).filter(
      anchor => anchor.kind !== entityAnchor.kind || anchor.id !== entityAnchor.id,
    ),
  ];
  return {
    ...mounted,
    scope: { tenant_id: mounted.scope.tenant_id, surface: 'profile360' },
    anchors,
    presentation: { ...mounted.presentation, view: 'table', page_size: 100 },
    truth: {
      ...mounted.truth,
      include_evidence: true,
      include_provenance: true,
    },
  };
}

export function useProfile360Exploration(entityId: string): Profile360ExplorationState {
  const client = useExplorationClient();
  const mountedContext = useExplorationContext();
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<Omit<Profile360ExplorationState, 'refetch'>>({
    status: entityId ? 'loading' : 'idle',
    data: null,
    truth: null,
    completeness: null,
    applicability: null,
    error: null,
  });
  const refetch = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    if (!entityId) {
      setState({
        status: 'idle',
        data: null,
        truth: null,
        completeness: null,
        applicability: null,
        error: null,
      });
      return;
    }

    let active = true;
    const controller = new AbortController();
    setState(current => ({ ...current, status: 'loading', error: null }));

    client
      .queryLatest<Profile360ExplorationData>(
        { context: profileContextFor(mountedContext, entityId), limit: 100 },
        {
          key: `profile360:${mountedContext.scope.tenant_id}:${entityId}`,
          signal: controller.signal,
        },
      )
      .then((envelope: ExplorationResultEnvelope<Profile360ExplorationData>) => {
        assertCanonicalTruthState(envelope.truth.overall_state);
        if (!active) return;
        setState({
          status: 'ready',
          data: envelope.data,
          truth: envelope.truth,
          completeness: envelope.completeness,
          applicability: envelope.applicability,
          error: null,
        });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setState({
          status: error instanceof RestClientError && error.status === 404 ? 'not_enabled' : 'error',
          data: null,
          truth: null,
          completeness: null,
          applicability: null,
          error: error instanceof Error ? error.message : 'Profile exploration failed',
        });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [client, entityId, mountedContext, revision]);

  return { ...state, refetch };
}
