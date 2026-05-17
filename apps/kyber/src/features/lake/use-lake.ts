import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useLakeGold(domain: string, entityId: string) {
  return useQuery({
    key: `lake:gold:${domain}:${entityId}`,
    fetcher: () => api.lake.gold(domain, entityId),
    staleTime: STALE,
    enabled: !!domain && !!entityId,
  });
}

export function useLakeQuality(domain: string) {
  return useQuery({
    key: `lake:quality:${domain}`,
    fetcher: () => api.lake.quality(domain),
    staleTime: STALE,
    enabled: !!domain,
  });
}

export function useLakeStatus() {
  return useQuery({
    key: 'lake:status',
    fetcher: () => api.lake.status(),
    staleTime: STALE,
  });
}

export function useLakeAudit(domain: string, sourceTag: string) {
  return useQuery({
    key: `lake:audit:${domain}:${sourceTag}`,
    fetcher: () => api.lake.audit(domain, sourceTag),
    staleTime: STALE,
    enabled: !!domain && !!sourceTag,
  });
}

export function useLakeIngest() {
  return useMutation({
    mutationFn: (params: { domain: string; source: string; source_tag: string; records: unknown[] }) =>
      api.lake.ingest(params),
  });
}

export function useLakeRollback() {
  return useMutation({
    mutationFn: (params: { domain: string; source_tag: string; tiers?: string[] }) =>
      api.lake.rollback(params),
  });
}

export function useLakeMaterialize() {
  return useMutation({
    mutationFn: (params: { domain: string; entity_id: string; metric: string; value: unknown; [k: string]: unknown }) =>
      api.lake.materialize(params),
  });
}
