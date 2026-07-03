import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useFraudStats() {
  return useQuery({
    key: 'fraud:stats',
    fetcher: () => api.fraud.stats(),
    staleTime: STALE,
  });
}

export function useFraudConfig() {
  return useQuery({
    key: 'fraud:config',
    fetcher: () => api.fraud.getConfig(),
    staleTime: STALE,
  });
}

export function useEvaluateFraud() {
  return useMutation({
    mutationFn: ({ event, context }: { event: Record<string, unknown>; context?: Record<string, unknown> }) =>
      api.fraud.evaluate(event, context),
  });
}

export function useEvaluateFraudBatch() {
  return useMutation({
    mutationFn: (events: unknown[]) => api.fraud.evaluateBatch(events),
  });
}

export function useUpdateFraudConfig() {
  return useMutation({
    mutationFn: (config: Record<string, unknown>) => api.fraud.updateConfig(config),
  });
}

export function useFraudNetworks(params?: { status?: string; limit?: number }) {
  return useQuery({
    key: `fraud-networks:${JSON.stringify(params)}`,
    fetcher: () => api.fraudNetworks.list(params),
    staleTime: STALE,
  });
}

export function useFraudNetworkDetail(networkId: string) {
  return useQuery({
    key: `fraud-network:${networkId}`,
    fetcher: () => api.fraudNetworks.get(networkId),
    staleTime: STALE,
    enabled: Boolean(networkId),
  });
}

export function useFraudNetworkGraph(networkId: string) {
  return useQuery({
    key: `fraud-network-graph:${networkId}`,
    fetcher: () => api.fraudNetworks.graph(networkId),
    staleTime: STALE,
    enabled: Boolean(networkId),
  });
}

export function useFraudNetworkMembers(networkId: string) {
  return useQuery({
    key: `fraud-network-members:${networkId}`,
    fetcher: () => api.fraudNetworks.members(networkId),
    staleTime: STALE,
    enabled: Boolean(networkId),
  });
}

export function useFraudNetworkEvidence(networkId: string) {
  return useQuery({
    key: `fraud-network-evidence:${networkId}`,
    fetcher: () => api.fraudNetworks.evidence(networkId),
    staleTime: STALE,
    enabled: Boolean(networkId),
  });
}

export function useBuildFraudNetwork() {
  return useMutation({
    mutationFn: (body: {
      anchor_entity_ids: string[];
      network_type: string;
      label?: string;
      notes?: string;
    }) => api.fraudNetworks.build(body),
  });
}

export function useFlowTraces(params?: { limit?: number }) {
  return useQuery({
    key: `flow-traces:${JSON.stringify(params)}`,
    fetcher: () => api.flowTrace.list(params),
    staleTime: STALE,
  });
}

export function useFlowTraceDetail(traceId: string) {
  return useQuery({
    key: `flow-trace:${traceId}`,
    fetcher: () => api.flowTrace.get(traceId),
    staleTime: STALE,
    enabled: Boolean(traceId),
  });
}

export function useFlowTracePaths(traceId: string) {
  return useQuery({
    key: `flow-trace-paths:${traceId}`,
    fetcher: () => api.flowTrace.paths(traceId),
    staleTime: STALE,
    enabled: Boolean(traceId),
  });
}

export function useCreateFlowTrace() {
  return useMutation({
    mutationFn: (body: {
      anchor_entity_id: string;
      direction: 'upstream' | 'downstream' | 'both';
      max_hops?: number;
      min_amount_usd?: number;
    }) => api.flowTrace.create(body),
  });
}

// ── Journey risk hooks (wired to durable decision APIs) ──────────────────────

export function useJourneyRisk(journeyId: string) {
  return useQuery({
    key: `journey-risk:${journeyId}`,
    fetcher: () => api.journeysMeasurement.risk(journeyId),
    staleTime: STALE,
    enabled: Boolean(journeyId),
  });
}

export function useJourneyFraudDecisions(journeyId: string, params?: { limit?: number }) {
  return useQuery({
    key: `journey-fraud-decisions:${journeyId}:${JSON.stringify(params)}`,
    fetcher: () => api.journeysMeasurement.journeyFraudDecisions(journeyId, params),
    staleTime: STALE,
    enabled: Boolean(journeyId),
  });
}

export function useJourneyFraudNetworks(journeyId: string) {
  return useQuery({
    key: `journey-fraud-networks:${journeyId}`,
    fetcher: () => api.journeysMeasurement.journeyFraudNetworks(journeyId),
    staleTime: STALE,
    enabled: Boolean(journeyId),
  });
}

export function useJourneyRiskExplain(journeyId: string) {
  return useQuery({
    key: `journey-risk-explain:${journeyId}`,
    fetcher: () => api.journeysMeasurement.riskExplain(journeyId),
    staleTime: STALE,
    enabled: Boolean(journeyId),
  });
}

export function useRecalculateJourneyRisk() {
  return useMutation({
    mutationFn: (journeyId: string) => api.journeysMeasurement.recalculateRisk(journeyId),
  });
}

// ── Fraud decision CRUD hooks ─────────────────────────────────────────────────

export function useFraudDecisions(params?: { risk_tier?: string; decision?: string; review_state?: string; limit?: number }) {
  return useQuery({
    key: `fraud-decisions:${JSON.stringify(params)}`,
    fetcher: () => api.fraudDecisions.list(params),
    staleTime: STALE,
  });
}

export function useFraudDecision(decisionId: string) {
  return useQuery({
    key: `fraud-decision:${decisionId}`,
    fetcher: () => api.fraudDecisions.get(decisionId),
    staleTime: STALE,
    enabled: Boolean(decisionId),
  });
}

export function useReviewFraudDecision() {
  return useMutation({
    mutationFn: ({ id, review_state, reviewed_by }: { id: string; review_state: string; reviewed_by: string }) =>
      api.fraudDecisions.review(id, { review_state, reviewed_by }),
  });
}

export function useSuppressFraudDecision() {
  return useMutation({
    mutationFn: ({ id, reviewed_by, suppression_reason }: { id: string; reviewed_by: string; suppression_reason: string }) =>
      api.fraudDecisions.suppress(id, { reviewed_by, suppression_reason }),
  });
}
