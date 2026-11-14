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
  type CampaignValue,
  type Row,
  type ValueEvent,
  type ValueWindow,
} from './value-model';

const STALE = 60_000;

const CAMPAIGN_LIMIT = 12;

export interface ValueEventsRead {
  readonly events: ValueEvent[];
  /** The backend reports the period read hit its server cap, so the events are not the whole period. */
  readonly truncated: boolean;
}

/**
 * Value-created events for one window. `start`/`end` scope the read on the
 * backend (GET /v1/billing/value-created), which reports `truncated` when its
 * bounded read may have missed events in the period.
 */
export function useValueEvents(tenant: string, window: ValueWindow, enabled = true) {
  const start = window.start.toISOString();
  const end = window.end.toISOString();
  return useQuery<ValueEventsRead>({
    key: `value:${tenant}:value-created:${start}:${end}`,
    fetcher: async () => {
      const payload = await api.billing.valueCreated({ start, end });
      return { events: parseValueEvents(payload), truncated: asRecord(payload)['truncated'] === true };
    },
    staleTime: STALE,
    enabled,
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
 * Imported campaigns plus each one's reconciled overview for the page
 * window. `time_start`/`time_end` scope spend and the observed population on
 * the backend; a campaign whose overview read fails keeps `overview: null`.
 */
export function useCampaignValues(tenant: string, window: ValueWindow, enabled = true) {
  const range = { time_start: window.start.toISOString(), time_end: window.end.toISOString() };
  return useQuery<CampaignValueRead>({
    key: `value:${tenant}:campaigns:${range.time_start}:${range.time_end}`,
    fetcher: async () => {
      const list = await api.campaigns.list({ limit: CAMPAIGN_LIMIT });
      const rows = asList(list.campaigns);
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
