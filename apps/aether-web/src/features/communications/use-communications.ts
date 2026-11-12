import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

/**
 * Communications page reads. Every hook wraps an endpoint that already exists
 * in `lib/api/endpoints.ts` (the `campaigns` Communications Intelligence calls
 * and the `comms` group); nothing here invents or derives a value.
 *
 * There is no tenant-wide "list communications" read yet, so the index walks
 * the tenant's communications campaigns (bounded fan-out) and reads each
 * campaign's provider messages. The result says how many campaigns it
 * scanned, skipped and failed to read so the page can disclose it.
 */

const STALE = 60_000;
const KEY = 'comms';

/** Campaign channels that are owned by a communications provider (same set Campaign 360 uses). */
export const COMMS_CAMPAIGN_CHANNELS: ReadonlySet<string> = new Set([
  'email', 'sms', 'push', 'lifecycle', 'transactional', 'in_app', 'in-app', 'inapp', 'outbound', 'agent',
]);

/** Upper bound on per-campaign message reads made by the index. */
export const COMMS_INDEX_MAX_CAMPAIGNS = 25;

type AnyRecord = Record<string, unknown>;

function asRecord(v: unknown): AnyRecord {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as AnyRecord) : {};
}

function asList(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

export interface CommsIndexCampaign {
  readonly raw: AnyRecord;
  readonly messages: readonly AnyRecord[] | null;
  readonly error: string | null;
}

export interface CommsIndex {
  /** Campaigns whose messages were read (or attempted). */
  readonly campaigns: readonly CommsIndexCampaign[];
  /** Communications campaigns found but not scanned (fan-out bound). */
  readonly skipped: number;
}

function campaignId(raw: AnyRecord): string {
  const id = raw.id ?? raw.campaign_id;
  return id === null || id === undefined ? '' : String(id);
}

export function isCommsCampaign(raw: AnyRecord): boolean {
  const channel = typeof raw.channel === 'string' ? raw.channel.trim().toLowerCase() : '';
  return COMMS_CAMPAIGN_CHANNELS.has(channel);
}

export async function fetchCommsIndex(): Promise<CommsIndex> {
  const list = await api.campaigns.list({ limit: 100 });
  const record = asRecord(list);
  const rows = asList(record.campaigns ?? record.data ?? list).map(asRecord).filter(r => campaignId(r) && isCommsCampaign(r));
  const scanned = rows.slice(0, COMMS_INDEX_MAX_CAMPAIGNS);
  const results = await Promise.allSettled(scanned.map(r => api.campaigns.messages(campaignId(r))));
  return {
    campaigns: scanned.map((raw, i) => {
      const result = results[i];
      if (result?.status === 'fulfilled') {
        return { raw, messages: asList(asRecord(result.value).items).map(asRecord), error: null };
      }
      const reason = result?.status === 'rejected' ? result.reason : null;
      return { raw, messages: null, error: reason instanceof Error ? reason.message : String(reason ?? 'Request failed') };
    }),
    skipped: rows.length - scanned.length,
  };
}

/** Tenant communications campaigns with their provider messages. */
export function useCommsIndex() {
  return useQuery({ key: `${KEY}:index`, fetcher: fetchCommsIndex, staleTime: STALE });
}

/** Tenant comms pipeline health (fact count, last event, machine-event share). */
export function useCommsHealth() {
  return useQuery({ key: `${KEY}:health`, fetcher: () => api.comms.health(), staleTime: 30_000 });
}

export function useCommsCampaign(campaignId: string) {
  return useQuery({
    key: `${KEY}:campaign:${campaignId}`,
    fetcher: () => api.campaigns.get(campaignId),
    staleTime: STALE,
    enabled: !!campaignId,
  });
}

/** One provider message: dimension record, engagement stats and link rollup. */
export function useCommsMessage(campaignId: string, externalMessageId: string) {
  return useQuery({
    key: `${KEY}:message:${campaignId}:${externalMessageId}`,
    fetcher: () => api.campaigns.messageDetail(campaignId, externalMessageId),
    staleTime: STALE,
    enabled: !!campaignId && !!externalMessageId,
  });
}

/** Campaign comms funnel with governed rate results (min sample, Wilson band, value state). */
export function useCommsFunnel(campaignId: string, enabled = true) {
  return useQuery({
    key: `${KEY}:funnel:${campaignId}`,
    fetcher: () => api.campaigns.commsFunnel(campaignId),
    staleTime: STALE,
    enabled: enabled && !!campaignId,
  });
}

export type RecipientStage = 'all' | 'delivered' | 'engaged' | 'replied';

export function useCommsRecipients(campaignId: string, stage: RecipientStage, enabled = true) {
  return useQuery({
    key: `${KEY}:recipients:${campaignId}:${stage}`,
    fetcher: () => api.campaigns.commsPopulation(campaignId, stage === 'all' ? { limit: 100 } : { stage, limit: 100 }),
    staleTime: STALE,
    enabled: enabled && !!campaignId,
  });
}

export function useCommsJourneys(campaignId: string, enabled = true) {
  return useQuery({
    key: `${KEY}:journeys:${campaignId}`,
    fetcher: () => api.campaigns.journeys(campaignId, { limit: 50 }),
    staleTime: STALE,
    enabled: enabled && !!campaignId,
  });
}

export function useCommsConversions(campaignId: string, enabled = true) {
  return useQuery({
    key: `${KEY}:conversions:${campaignId}`,
    fetcher: () => api.campaigns.conversions(campaignId, { limit: 100 }),
    staleTime: STALE,
    enabled: enabled && !!campaignId,
  });
}
