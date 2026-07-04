import { describe, expect, it } from 'vitest';
import { buildAgenticObservation, makeAgenticObserver, toServerEvent } from './agentic';
import type { ServerEvent } from './types';

describe('agentic observation helpers', () => {
  it('builds Contract v2 events with event_type and no execution claim', () => {
    const event = buildAgenticObservation({
      tenant_id: 'tenant-a',
      event_type: 'agent_tool_invocation_observed',
      agent: { agent_id: 'agent-1', runtime_id: 'runtime-1' },
      runtime: { runtime_id: 'runtime-1', sdk_name: '@aether/server' },
      correlation: { trace_id: 'trace-1', invocation_id: 'invoke-1' },
      mcp: { tool_name: 'x.create_post', tool_id: 'tool-1', arguments_policy: 'metadata_only' },
      authorization: { authorization_id: 'auth-1', external_account_id: 'acct-1', credential_ref: 'vault://auth-1', scopes: ['tweet.write'] },
      object: { object_type: 'tool', object_id: 'tool-1' },
      action: { name: 'tool_invocation_observed', status: 'observed' },
      economics: { amount: 1, currency: 'USD' },
    });

    expect(event.schema_version).toBe('2.0');
    expect(event.event_type).toBe('agent_tool_invocation_observed');
    expect(event.event_name).toBe(event.event_type);
    expect(event.economics?.is_execution_by_aether).toBe(false);
    expect(event.authorization?.credential_ref).toBe('vault://auth-1');
    expect(event.authorization).not.toHaveProperty('access_token');
  });

  it('converts Contract v2 events to ServerEvent payloads for batching', () => {
    const event = buildAgenticObservation({
      tenant_id: 'tenant-a',
      event_type: 'agent_activity_observed',
      object: { object_type: 'agent', object_id: 'agent-1' },
      action: { name: 'agent_observed', status: 'observed' },
    });
    const serverEvent = toServerEvent(event);
    expect(serverEvent.type).toBe('agent_activity_observed');
    expect(serverEvent.messageId).toBe(event.event_id);
    expect(serverEvent.properties?.execution_by_aether).toBe(false);
    expect(serverEvent.properties?.agentic_contract_version).toBe('2.0');
  });

  it('exposes named helpers for MCP, authorization, provider action, and verification observations', () => {
    const events: ServerEvent[] = [];
    const observer = makeAgenticObserver((event) => events.push(event));

    observer.observeMcpConnection({ tenant_id: 'tenant-a', connection_id: 'conn-1', server_name: 'x-tools', agent_id: 'agent-1' });
    observer.observeAuthorization({ tenant_id: 'tenant-a', authorization_id: 'auth-1', external_account_id: 'acct-1', scopes: ['tweet.write'], agent_id: 'agent-1' });
    observer.observeProviderAction({ tenant_id: 'tenant-a', provider_action_id: 'act-1', provider_request_id: 'req-1', external_object_id: 'obj-1', agent_id: 'agent-1' });
    observer.observeProviderVerification({ tenant_id: 'tenant-a', verification_id: 'ver-1', provider_request_id: 'req-1', external_object_id: 'obj-1', status: 'provider_confirmed' });

    expect(events.map((event) => event.type)).toEqual([
      'agent_mcp_connection_observed',
      'agent_permission_observed',
      'agent_tool_invocation_observed',
      'agent_activity_observed',
    ]);
    for (const event of events) {
      expect(event.properties?.execution_by_aether).toBe(false);
    }
  });
});
