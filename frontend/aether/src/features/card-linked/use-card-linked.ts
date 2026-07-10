import { useQuery } from '@aether/ui';
import { cardLinkedApi, type CardLinkedFilters } from './api';

const STALE = 30_000;

export function useCardLinkedFlows(filters: CardLinkedFilters = {}) {
  return useQuery({
    key: `card-linked:flows:${JSON.stringify(filters)}`,
    fetcher: () => cardLinkedApi.flows(filters),
    staleTime: STALE,
  });
}

export function useCardLinkedCatalog(entityType?: string) {
  return useQuery({
    key: `card-linked:catalog:${entityType ?? 'all'}`,
    fetcher: () => cardLinkedApi.catalog(entityType),
    staleTime: 300_000,
  });
}

export function useCardLinkedCampaignOutcomes(campaignId: string) {
  return useQuery({
    key: `card-linked:campaign:${campaignId}`,
    fetcher: () => cardLinkedApi.campaignOutcomes(campaignId),
    staleTime: STALE,
    enabled: !!campaignId,
  });
}

export function useCardLinkedProfileActivity(entityId: string, filters: CardLinkedFilters = {}) {
  return useQuery({
    key: `card-linked:profile:${entityId}:${JSON.stringify(filters)}`,
    fetcher: () => cardLinkedApi.profileActivity(entityId, filters),
    staleTime: STALE,
    enabled: !!entityId,
  });
}
