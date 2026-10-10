import { useQuery } from '@aether/ui';
import { z } from 'zod';
import { restClient } from '@aether-app/lib/api/rest/client';

const responseSchema = z.object({
  data: z.record(z.unknown()),
  status: z.string(),
  timestamp: z.string(),
}).passthrough();

export type Agent360Profile = z.infer<typeof responseSchema>['data'];

export function useAgent360(agentId: string) {
  return useQuery({
    key: `agent-360:${agentId}`,
    fetcher: () => restClient
      .get(`/v1/profile/${encodeURIComponent(agentId)}/agent`, responseSchema)
      .then(response => response.data),
    enabled: Boolean(agentId),
    staleTime: 30_000,
  });
}
