import { z } from 'zod';
import { restClient } from '@aether-app/lib/api/rest/client';

type AnyRecord = Record<string, any>;

const unknownSchema = z.unknown();
const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });

const buildQS = (params: Record<string, string | number | boolean | undefined>): string => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
};

export function fetchTenantSuggestions(params?: {
  readonly status?: string;
  readonly priority?: string;
  readonly limit?: number;
  readonly offset?: number;
}): Promise<AnyRecord[]> {
  return restClient
    .get(`/v1/aether/suggestions${buildQS({ ...params })}`, wrap(z.array(unknownSchema)))
    .then(r => r.data as AnyRecord[]);
}

export function fetchTenantSuggestion(id: string): Promise<AnyRecord> {
  return restClient
    .get(`/v1/aether/suggestions/${encodeURIComponent(id)}`, wrap(unknownSchema))
    .then(r => r.data as AnyRecord);
}

export function submitFeedback(
  id: string,
  feedback: 'helpful' | 'not_helpful' | 'dismissed',
): Promise<void> {
  return restClient
    .post(
      `/v1/aether/suggestions/${encodeURIComponent(id)}/feedback`,
      wrap(unknownSchema),
      { feedback },
    )
    .then(() => undefined);
}
