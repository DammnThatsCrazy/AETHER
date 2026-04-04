import { z } from 'zod';
import { getAccessToken } from '@shiki/features/auth';
import { env, getEnvironment } from '@shiki/lib/env';
import { log } from '@shiki/lib/logging';

export class GraphQLClientError extends Error {
  constructor(
    message: string,
    public readonly errors: readonly GraphQLError[],
    public readonly correlationId: string,
  ) {
    super(message);
    this.name = 'GraphQLClientError';
  }
}

interface GraphQLError {
  readonly message: string;
  readonly locations?: readonly { readonly line: number; readonly column: number }[] | undefined;
  readonly path?: readonly string[] | undefined;
}

const graphqlResponseSchema = z.object({
  data: z.unknown().nullable(),
  errors: z.array(z.object({
    message: z.string(),
    locations: z.array(z.object({ line: z.number(), column: z.number() })).optional(),
    path: z.array(z.string()).optional(),
  })).optional(),
});

let requestCounter = 0;

export async function graphqlQuery<T>(
  query: string,
  variables: Record<string, unknown> | undefined,
  schema: z.ZodType<T>,
  operationName?: string,
): Promise<T> {
  const correlationId = `shiki-gql-${Date.now()}-${++requestCounter}`;
  const url = env.VITE_GRAPHQL_URL;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Correlation-ID': correlationId,
    'X-Shiki-Environment': getEnvironment(),
  };

  const token = getAccessToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const startTime = performance.now();

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({ query, variables, operationName }),
    });

    const duration = Math.round(performance.now() - startTime);
    log.info(`[GraphQL] ${operationName ?? 'query'} -> ${response.status} (${duration}ms)`, { correlationId });

    const json: unknown = await response.json();
    const envelope = graphqlResponseSchema.parse(json);

    if (envelope.errors && envelope.errors.length > 0) {
      throw new GraphQLClientError(
        envelope.errors.map(e => e.message).join('; '),
        envelope.errors as readonly GraphQLError[],
        correlationId,
      );
    }

    const parsed = schema.safeParse(envelope.data);
    if (!parsed.success) {
      log.error(`[GraphQL] Schema validation failed`, { correlationId, errors: parsed.error.issues });
      throw new GraphQLClientError(
        `Response validation failed: ${parsed.error.issues.map(i => i.message).join(', ')}`,
        [],
        correlationId,
      );
    }

    return parsed.data;
  } catch (err) {
    if (err instanceof GraphQLClientError) throw err;
    throw new GraphQLClientError(
      err instanceof Error ? err.message : 'GraphQL request failed',
      [],
      correlationId,
    );
  }
}
