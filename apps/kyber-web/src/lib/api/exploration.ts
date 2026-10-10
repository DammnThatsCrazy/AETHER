import { z } from 'zod';
import {
  createExplorationClient,
  type ExplorationApiResponse,
  type ExplorationTransport,
  type ExplorationTransportRequest,
} from '@aether/ui/exploration';
import { restClient } from './rest/client';

const responseSchema = z.object({ data: z.unknown() }).passthrough();

const transport: ExplorationTransport = async <T>(request: ExplorationTransportRequest) => {
  const { method, path, body, signal } = request;
  const options = { signal };
  const response =
    method === 'GET'
      ? await restClient.get(path, responseSchema, options)
      : method === 'DELETE'
        ? await restClient.delete(path, responseSchema, options)
        : await restClient.post(path, responseSchema, body, options);
  return response as ExplorationApiResponse<T>;
};

/** Canonical exploration client using Kyber's cookie and CSRF REST transport. */
export const explorationClient = createExplorationClient(transport);
