import { describe, it, expect, vi, beforeEach } from 'vitest';
import { EVENT_FAMILY } from '@aether/shared';
import type { AgentDeploymentContext } from '@aether/shared';
import { AgentTelemetryClient, validateAgentDeploymentContext } from './agent-telemetry';
import { sendBatch } from './transport';

vi.mock('./transport', () => ({
  sendBatch: vi.fn(async () => ({ ok: true, status: 200 })),
}));

const mockedSendBatch = vi.mocked(sendBatch);

const deployment: AgentDeploymentContext = {
  deploymentId: 'dep-1',
  agentId: 'agent-1',
  externalPlatform: 'discord_bot',
  environment: 'production',
  consentMode: 'tenant_managed',
};

function makeClient(overrides: Partial<AgentDeploymentContext> = {}) {
  return new AgentTelemetryClient({
    writeKey: 'test-key',
    endpoint: 'http://localhost/v1/batch',
    deployment: { ...deployment, ...overrides },
  });
}

function sentEvents(): Array<Record<string, any>> {
  return mockedSendBatch.mock.calls.flatMap((call) => call[1] as Array<Record<string, any>>);
}

beforeEach(() => {
  mockedSendBatch.mockClear();
});

describe('validateAgentDeploymentContext', () => {
  it('accepts a valid deployment context', () => {
    expect(() => validateAgentDeploymentContext(deployment)).not.toThrow();
  });

  it('rejects a missing deployment context', () => {
    expect(() => validateAgentDeploymentContext(undefined as any)).toThrow('requires config.deployment');
  });

  it('rejects missing deploymentId and agentId', () => {
    expect(() => validateAgentDeploymentContext({ ...deployment, deploymentId: '' })).toThrow(
      'AgentDeploymentContext.deploymentId is required',
    );
    expect(() => validateAgentDeploymentContext({ ...deployment, agentId: undefined as any })).toThrow(
      'AgentDeploymentContext.agentId is required',
    );
  });

  it('rejects an unknown externalPlatform', () => {
    expect(() =>
      validateAgentDeploymentContext({ ...deployment, externalPlatform: 'fax_machine' as any }),
    ).toThrow('externalPlatform "fax_machine" is invalid');
  });

  it('rejects an unknown environment', () => {
    expect(() =>
      validateAgentDeploymentContext({ ...deployment, environment: 'prod' as any }),
    ).toThrow('environment "prod" is invalid');
  });

  it('rejects an unknown consentMode', () => {
    expect(() =>
      validateAgentDeploymentContext({ ...deployment, consentMode: 'nobody_managed' as any }),
    ).toThrow('consentMode "nobody_managed" is invalid');
  });
});

describe('AgentTelemetryClient construction', () => {
  it('constructs with a valid deployment context', async () => {
    const client = makeClient();
    expect(client.getDeployment().deploymentId).toBe('dep-1');
    await client.shutdown();
  });

  it('throws at construction on an invalid deployment context', () => {
    expect(() => makeClient({ externalPlatform: 'carrier_pigeon' as any })).toThrow(
      'externalPlatform "carrier_pigeon" is invalid',
    );
  });
});

describe('deployment context attachment', () => {
  it('attaches context.agentDeployment to every emitted event', async () => {
    const client = makeClient();
    client.track({ type: 'agent_activity_observed', properties: { note: 'hi' } });
    client.interaction({ name: 'message_received' });
    await client.flush();
    const events = sentEvents();
    expect(events.length).toBe(2);
    for (const event of events) {
      expect(event.context.agentDeployment).toEqual({
        deploymentId: 'dep-1',
        agentId: 'agent-1',
        externalPlatform: 'discord_bot',
        environment: 'production',
        consentMode: 'tenant_managed',
      });
    }
    await client.shutdown();
  });

  it('preserves caller-supplied context alongside agentDeployment', async () => {
    const client = makeClient();
    client.track({ type: 'track', context: { locale: 'en-US' } });
    await client.flush();
    const [event] = sentEvents();
    expect(event.context.locale).toBe('en-US');
    expect(event.context.agentDeployment.agentId).toBe('agent-1');
    await client.shutdown();
  });
});

describe('canonical_entity_id stripping', () => {
  it('strips canonical_entity_id from properties and context, including nested', async () => {
    const client = makeClient();
    client.track({
      type: 'track',
      properties: {
        canonical_entity_id: 'ent-1',
        canonicalEntityId: 'ent-2',
        nested: { canonical_entity_id: 'ent-3', keep: 'yes' },
      },
      context: { canonical_entity_id: 'ent-4', locale: 'en-US' },
    });
    await client.flush();
    const [event] = sentEvents();
    expect(event.properties.canonical_entity_id).toBeUndefined();
    expect(event.properties.canonicalEntityId).toBeUndefined();
    expect(event.properties.nested.canonical_entity_id).toBeUndefined();
    expect(event.properties.nested.keep).toBe('yes');
    expect(event.context.canonical_entity_id).toBeUndefined();
    expect(event.context.locale).toBe('en-US');
    await client.shutdown();
  });
});

describe('typed emit helpers', () => {
  it('emit only canonical event types', async () => {
    const client = makeClient();
    client.interaction({ name: 'message_received' });
    client.task({ taskId: 't-1', status: 'started' });
    client.task({ taskId: 't-1', status: 'completed', durationMs: 12 });
    client.task({ taskId: 't-2', status: 'failed', errorCode: 'timeout' });
    client.toolInvocation({ toolName: 'search', status: 'succeeded_observed', durationMs: 5 });
    client.walletObservation({ kind: 'wallet', address: '0xabc' });
    client.walletObservation({ kind: 'transaction', transactionHash: '0xdef' });
    client.paymentObservation({ status: 'initiated', amount: 5, currency: 'USD' });
    client.paymentObservation({ status: 'completed', amount: 5, currency: 'USD' });
    client.paymentObservation({ status: 'failed', errorCode: 'declined' });
    client.outcomeRecorded({ outcome: 'resolved', taskId: 't-1', success: true });
    client.riskSignal({ riskLevel: 'high', reasonCodes: ['exceeded_tool_budget'] });
    await client.flush();

    const types = sentEvents().map((e) => e.type);
    expect(types).toEqual([
      'track',
      'agent_task_started',
      'agent_task_completed',
      'agent_task_failed',
      'agent_tool_invocation_observed',
      'wallet',
      'transaction',
      'payment_initiated',
      'payment_completed',
      'payment_failed',
      'agent_outcome_recorded',
      'agent_risk_signal_observed',
    ]);
    // Every emitted type must exist in the shared canonical registry.
    for (const type of types) {
      expect(EVENT_FAMILY[type as keyof typeof EVENT_FAMILY]).toBeDefined();
    }
    await client.shutdown();
  });

  it('carries helper params into scrubbed properties', async () => {
    const client = makeClient();
    client.toolInvocation({ toolName: 'search', properties: { api_key: 'sk-secret' } });
    await client.flush();
    const [event] = sentEvents();
    expect(event.properties.toolName).toBe('search');
    expect(event.properties.status).toBe('observed');
    // Inherited scrubber redacts sensitive keys before transmission.
    expect(event.properties.api_key).toBe('[REDACTED]');
    await client.shutdown();
  });

  it('emits run, trigger, policy, delegation, and outcome references as source telemetry', async () => {
    const client = makeClient();
    client.task({
      taskId: 'task-1',
      runId: 'run-1',
      status: 'started',
      triggerId: 'trigger-1',
      triggerType: 'webhook',
      actionId: 'action-1',
      actionType: 'issue.update',
    });
    client.toolInvocation({
      toolName: 'browser.search',
      taskId: 'task-1',
      runId: 'run-1',
      status: 'succeeded_observed',
      mcpServerName: 'browser-mcp',
    });
    client.policyEvaluated({
      runId: 'run-1',
      taskId: 'task-1',
      decisionId: 'decision-1',
      actionId: 'action-1',
      actionType: 'issue.update',
      triggerId: 'trigger-1',
      triggerType: 'webhook',
      policyId: 'policy-1',
      policyVersion: '4',
      decision: 'allow',
      reasonCodes: ['within_scope'],
    });
    client.delegatedTask({
      runId: 'run-1',
      taskId: 'task-1',
      delegationId: 'delegation-1',
      delegatedToAgentId: 'external-agent-2',
      delegatedToNamespace: 'vendor.runtime',
      actionId: 'action-1',
      triggerId: 'trigger-1',
    });
    client.outcomeRecorded({
      outcomeId: 'outcome-1',
      outcome: 'completed',
      taskId: 'task-1',
      runId: 'run-1',
      success: true,
    });
    await client.flush();

    const events = sentEvents();
    expect(events.map((event) => event.type)).toEqual([
      'agent_task_started',
      'agent_tool_invocation_observed',
      'agent_policy_evaluated',
      'agent_delegated_task',
      'agent_outcome_recorded',
    ]);
    const [task, tool, policy, delegation, outcome] = events;
    expect(task.properties).toMatchObject({
      taskId: 'task-1', runId: 'run-1', triggerId: 'trigger-1',
      triggerType: 'webhook', actionId: 'action-1', actionType: 'issue.update',
    });
    expect(tool.properties).toMatchObject({
      toolName: 'browser.search', taskId: 'task-1', runId: 'run-1',
      status: 'succeeded_observed', mcpServerName: 'browser-mcp',
    });
    expect(policy.properties).toMatchObject({
      runId: 'run-1', decisionId: 'decision-1', policyId: 'policy-1',
      policyVersion: '4', decision: 'allow', reasonCodes: ['within_scope'],
    });
    expect(delegation.properties).toMatchObject({
      runId: 'run-1', delegationId: 'delegation-1',
      delegatedToAgentId: 'external-agent-2', delegatedToNamespace: 'vendor.runtime',
      actionId: 'action-1',
    });
    expect(outcome.properties).toMatchObject({
      outcomeId: 'outcome-1', outcome: 'completed', taskId: 'task-1',
      runId: 'run-1', success: true,
    });
    for (const event of events) {
      expect(event.context.agentDeployment.deploymentId).toBe('dep-1');
      expect(EVENT_FAMILY[event.type as keyof typeof EVENT_FAMILY]).toBeDefined();
    }
    await client.shutdown();
  });
});

describe('batching and consent passthrough', () => {
  it('delivers via the existing queue/transport batching path', async () => {
    const client = makeClient();
    client.interaction({ name: 'ping' });
    expect(mockedSendBatch).not.toHaveBeenCalled();
    await client.flush();
    expect(mockedSendBatch).toHaveBeenCalledTimes(1);
    const [config] = mockedSendBatch.mock.calls[0];
    expect(config.endpoint).toBe('http://localhost/v1/batch');
    expect(config.writeKey).toBe('test-key');
    await client.shutdown();
  });

  it('passes granted consents with each batch', async () => {
    const client = makeClient();
    client.grant(['agent', 'analytics']);
    client.interaction({ name: 'ping' });
    await client.flush();
    const [, , consents] = mockedSendBatch.mock.calls[0];
    expect(consents).toContain('agent');
    expect(consents).toContain('analytics');
    expect(consents).not.toContain('credit');
    await client.shutdown();
  });
});

describe('agent behavior helpers', () => {
  it('maps behavior steps onto registered agent event types with the deployment attached', async () => {
    const client = makeClient();
    client.objective({ objectiveId: 'o1', status: 'created', ownerActorId: 'person-1', goal: 'buy' });
    client.decision({ decisionId: 'd1', phase: 'started', objectiveId: 'o1' });
    client.decision({ decisionId: 'd1', phase: 'candidate_considered', candidateId: 'sku-1', amount: '12.50' });
    client.decision({ decisionId: 'd1', phase: 'candidate_rejected', candidateId: 'sku-2', reason: 'price' });
    client.decision({ decisionId: 'd1', phase: 'action_selected', candidateId: 'sku-1' });
    client.authorization({ authorizationId: 'az1', status: 'denied', decisionId: 'd1' });
    client.toolAdaptation({ kind: 'switched', toolName: 'b', fromToolName: 'a' });
    client.execution({ status: 'aborted', decisionId: 'd1' });
    client.economic({ kind: 'quote_received', amount: '10', currency: 'USD' });
    client.information({ kind: 'source_consulted', sourceRef: 'web:reviews', trust: 'external' });
    client.memory({ memoryId: 'm1', op: 'invalidated' });
    client.spawned({ childAgentId: 'child-1', runId: 'r1' });
    client.terminated();
    client.decision({ decisionId: 'd1', phase: 'completed', outcome: 'purchased' });
    await client.flush();
    const events = sentEvents();
    expect(events.map((e) => e.type)).toEqual([
      'agent_objective_created', 'agent_decision_started', 'agent_candidate_considered',
      'agent_candidate_rejected', 'agent_action_selected', 'agent_authorization_denied',
      'agent_tool_switched', 'agent_execution_aborted', 'agent_quote_received',
      'agent_source_consulted', 'agent_memory_invalidated', 'agent_subagent_spawned',
      'agent_terminated', 'agent_decision_completed',
    ]);
    for (const e of events) {
      expect(EVENT_FAMILY[e.type as keyof typeof EVENT_FAMILY]).toBe('agent');
      expect(e.context.agentDeployment.deploymentId).toBe('dep-1');
    }
    expect(events[11].properties.parentAgentId).toBe('agent-1');
  });

  it('rejects non-decimal amounts', () => {
    const client = makeClient();
    expect(() => client.economic({ kind: 'transaction_initiated', amount: 12.5 as unknown as string }))
      .toThrow(TypeError);
    expect(() => client.decision({ decisionId: 'd', phase: 'candidate_considered', amount: '1e9' }))
      .toThrow(TypeError);
  });
});
