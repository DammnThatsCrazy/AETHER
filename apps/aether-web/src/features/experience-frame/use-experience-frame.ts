/**
 * Reads one governed 360 frame for a subject through the authenticated REST
 * client. The tenant comes from the session, never from this hook's input.
 */

import { useQuery } from '@aether/ui';
import { useGraphContext } from '@aether/ui/exploration';
import { restClient } from '@aether-app/lib/api/rest/client';
import {
  experienceFrameResponseSchema,
  type ExperienceFrameRequest,
} from './experience-frame-types';

export function useExperienceFrame(request: ExperienceFrameRequest, options?: { readonly enabled?: boolean }) {
  const { scope } = useGraphContext();
  const tenantId = scope.tenant_id;
  const slotKey = request.requestedSlotIds?.join(',') ?? '';
  return useQuery({
    key: `experience-frame:${encodeURIComponent(tenantId)}:${request.surfaceId}:${encodeURIComponent(request.subject.kind)}:${encodeURIComponent(request.subject.id)}:${slotKey}:${request.asOf ?? ''}`,
    fetcher: () => restClient.post(
      '/v1/experience360/frames',
      experienceFrameResponseSchema,
      {
        surfaceId: request.surfaceId,
        subject: request.subject,
        ...(request.requestedSlotIds ? { requestedSlotIds: [...request.requestedSlotIds] } : {}),
        ...(request.asOf ? { asOf: request.asOf } : {}),
      },
    ),
    enabled: Boolean(tenantId && request.subject.id && (options?.enabled ?? true)),
    staleTime: 30_000,
  });
}
