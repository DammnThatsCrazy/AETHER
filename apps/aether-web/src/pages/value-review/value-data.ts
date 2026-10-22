/**
 * Tenant-scoped reads behind the Value page tabs. Keys carry the tenant id the
 * value-review overview returned, so a tenant switch never serves another
 * tenant's cached rows.
 */
import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import {
  asList,
  asRecord,
  parseCampaignOverview,
  parseValueEvents,
  str,
  windowRange,
  type CampaignValue,
  type Row,
  type ValueEvent,
} from './value-model';

const STALE = 60_000;

/** Upper bound the value-created read returns when no period is passed (backend `limit=100`). */
export const VALUE_EVENT_READ_LIMIT = 100;
const CAMPAIGN_LIMIT = 12;

export function useValueEvents(tenant: string) {
  return useQuery<ValueEvent[]>({
    key: `value:${tenant}:value-created`,
    fetcher: async () => parseValueEvents(await api.billing.valueCreated()),
    staleTime: STALE,
  });
}

export function useOutcomeLedgerRead(tenant: string, enabled = true) {
  return useQuery<Row>({
    key: `value:${tenant}:outcome-ledger`,
    fetcher: async () => asRecord(await api.intelligence.outcomeLedger()),
    staleTime: STALE,
    enabled,
  });
}

export interface CampaignValueRead {
  readonly total: number;
  /** True when the campaign list has more pages than the first CAMPAIGN_LIMIT read here. */
  readonly partial: boolean;
  readonly items: readonly CampaignValue[];
}

/**
 * Imported campaigns plus each one's reconciled overview for the selected
 * window. `time_start`/`time_end` scope spend and the observed population on
 * the backend; a campaign whose overview read fails keeps `overview: null`.
 */
export function useCampaignValues(tenant: string, days: number, enabled = true) {
  return useQuery<CampaignValueRead>({
    key: `value:${tenant}:campaigns:${days}d`,
    fetcher: async () => {
      const list = await api.campaigns.list({ limit: CAMPAIGN_LIMIT });
      const rows = asList(list.campaigns);
      const range = windowRange(days);
      const settled = await Promise.allSettled(
        rows.map(row => {
          const id = str(row['id'] ?? row['campaign_id']);
          return id ? api.campaigns.overview(id, range) : Promise.reject(new Error('campaign has no id'));
        }),
      );
      const items = rows.map((row, index): CampaignValue => {
        const result = settled[index];
        return {
          id: str(row['id'] ?? row['campaign_id']) ?? '',
          name: str(row['name']) ?? str(row['id'] ?? row['campaign_id']) ?? 'Unnamed campaign',
          platform: str(row['platform'] ?? row['origin'] ?? row['source']),
          status: str(row['status']),
          overview: result && result.status === 'fulfilled' ? parseCampaignOverview(result.value) : null,
        };
      });
      return { total: items.length, partial: list.has_more === true, items };
    },
    staleTime: STALE,
    enabled,
  });
}
