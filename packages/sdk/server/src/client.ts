// Typed event emitters for common server observation patterns.
// All methods return this for chaining; events are batched via AetherServerSDK.

import type { ServerEvent } from './types';

type TrackFn = (event: ServerEvent) => void;

export function makeServerClient(track: TrackFn) {
  return {
    /** Observe an API request lifecycle. */
    apiRequest(params: {
      method: string;
      path: string;
      statusCode: number;
      durationMs: number;
      userId?: string;
      tenantId?: string;
      errorCode?: string;
    }): void {
      track({
        type: 'api_request_observed',
        userId: params.userId,
        properties: {
          method: params.method,
          path: params.path,
          statusCode: params.statusCode,
          durationMs: params.durationMs,
          tenantId: params.tenantId,
          errorCode: params.errorCode,
        },
      });
    },

    /** Observe a webhook delivery attempt. */
    webhookDelivery(params: {
      webhookId: string;
      event: string;
      statusCode: number;
      durationMs: number;
      attempt: number;
      tenantId?: string;
    }): void {
      track({
        type: 'webhook_delivery_observed',
        properties: {
          webhookId: params.webhookId,
          event: params.event,
          statusCode: params.statusCode,
          durationMs: params.durationMs,
          attempt: params.attempt,
          tenantId: params.tenantId,
        },
      });
    },

    /** Observe a background job execution. */
    job(params: {
      jobType: string;
      status: 'started' | 'completed' | 'failed';
      durationMs?: number;
      errorCode?: string;
      tenantId?: string;
    }): void {
      const type = params.status === 'started'
        ? 'job_started'
        : params.status === 'completed' ? 'job_completed' : 'job_failed';
      track({
        type,
        properties: {
          jobType: params.jobType,
          durationMs: params.durationMs,
          errorCode: params.errorCode,
          tenantId: params.tenantId,
        },
      });
    },

    /** Observe a connector sync lifecycle event. */
    connectorSync(params: {
      connectorId: string;
      status: 'started' | 'completed' | 'failed';
      recordsProcessed?: number;
      errorCode?: string;
      tenantId?: string;
    }): void {
      const type = params.status === 'started'
        ? 'connector_sync_started'
        : params.status === 'completed' ? 'connector_sync_completed' : 'connector_sync_failed';
      track({
        type,
        properties: {
          connectorId: params.connectorId,
          recordsProcessed: params.recordsProcessed,
          errorCode: params.errorCode,
          tenantId: params.tenantId,
        },
      });
    },

    /** Observe a rate limit hit. */
    rateLimit(params: {
      path: string;
      limitType: string;
      retryAfterMs: number;
      tenantId?: string;
    }): void {
      track({
        type: 'rate_limit_observed',
        properties: {
          path: params.path,
          limitType: params.limitType,
          retryAfterMs: params.retryAfterMs,
          tenantId: params.tenantId,
        },
      });
    },

    /** Observe a dependency (downstream service) failure. */
    dependencyFailure(params: {
      dependency: string;
      errorCode: string;
      durationMs?: number;
      tenantId?: string;
    }): void {
      track({
        type: 'dependency_failure_observed',
        properties: {
          dependency: params.dependency,
          errorCode: params.errorCode,
          durationMs: params.durationMs,
          tenantId: params.tenantId,
        },
      });
    },
  };
}
