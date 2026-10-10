import { describe, expect, it } from 'vitest';

import { AetherMobileClient } from '../index';
import type { FetchLike, FetchRequestInit, KyberSessionView, StepUpVerifyInput } from '../index';

interface RecordedCall {
  url: string;
  init: FetchRequestInit;
}

function stubClient(
  responder: (call: RecordedCall) => { status: number; body: unknown },
  token: string | null = 'tok-123',
) {
  const calls: RecordedCall[] = [];
  const fetch: FetchLike = async (url, init) => {
    const call = { url, init };
    calls.push(call);
    const { status, body } = responder(call);
    return {
      status,
      json: async () => body,
      text: async () => JSON.stringify(body),
    };
  };
  const client = new AetherMobileClient(
    { apiBaseUrl: 'https://api.aether.test/', appKind: 'kyber', environment: 'production' },
    { fetch, auth: { getAccessToken: async () => token } },
  );
  return { client, calls };
}

const sessionBody: KyberSessionView = {
  session_id: 'sess_1',
  operator_id: 'operator-1',
  device_id: 'dev_1',
  status: 'active',
  authentication_strength: 'step_up',
  authentication_methods: ['proof_key'],
  environment: 'production',
  presence_expires_at: '2026-08-07T01:00:00Z',
  authority_expires_at: '2026-08-07T02:00:00Z',
  idle_expires_at: '2026-08-07T00:30:00Z',
  created_at: '2026-08-07T00:00:00Z',
  last_seen_at: '2026-08-07T00:01:00Z',
  rotated_at: null,
  revoked_at: null,
  risk_state: 'normal',
  step_up: { fresh: true, grant_id: 'grant_1', expires_at: '2026-08-07T01:00:00Z' },
};

describe('AetherMobileClient Kyber methods', () => {
  it('reads the current Kyber session, unwrapping the APIResponse envelope', async () => {
    const { client, calls } = stubClient(() => ({ status: 200, body: { data: sessionBody } }));
    const session = await client.getSession();
    expect(session.session_id).toBe('sess_1');
    expect(session.step_up?.grant_id).toBe('grant_1');
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/auth/session');
    expect(calls[0].init.method).toBe('GET');
  });

  it('reads the mobile actions digest', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: {
        data: {
          tiers: { tier0: [], tier1: [], tier2: [], tier3: [] },
          counts: { tier0: 0, tier1: 0, tier2: 0, tier3: 0 },
          step_up_required: true,
          step_up: { fresh: false, grant_id: null, expires_at: null },
          generated_at: '2026-08-07T00:00:00Z',
        },
      },
    }));
    const digest = await client.getActions();
    expect(digest.counts.tier0).toBe(0);
    expect(digest.step_up_required).toBe(true);
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/mobile/actions');
    expect(calls[0].init.method).toBe('GET');
  });

  it('requests step-up options with an optional capability_id', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: {
        data: {
          challenge_id: 'chal_1',
          challenge: 'cmVxdWVzdGVkLWNoYWxsZW5nZQ',
          device_id: 'dev_1',
          capability_id: 'kyber.workforce.execute',
        },
      },
    }));
    const options = await client.requestStepUpOptions('dev_1', 'kyber.workforce.execute');
    expect(options.challenge_id).toBe('chal_1');
    expect(options.device_id).toBe('dev_1');
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/auth/step-up/options');
    expect(calls[0].init.method).toBe('POST');
    expect(JSON.parse(calls[0].init.body ?? '{}')).toEqual({ capability_id: 'kyber.workforce.execute' });
  });

  it('requests step-up options omitting capability_id when not supplied', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: {
        data: { challenge_id: 'chal_2', challenge: 'c2lnbmF0dXJlLXJlcXVlc3Q', device_id: 'dev_1', capability_id: null },
      },
    }));
    const options = await client.requestStepUpOptions('dev_1');
    expect(options.challenge_id).toBe('chal_2');
    expect(JSON.parse(calls[0].init.body ?? '{}')).toEqual({});
  });

  it('verifies a step-up assertion, sending the input verbatim', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: {
        data: {
          grant_id: 'grant_1',
          capability_id: 'kyber.workforce.execute',
          expires_at: '2026-08-07T01:00:00Z',
          session: sessionBody,
        },
      },
    }));
    const input: StepUpVerifyInput = {
      challenge_id: 'chal_1',
      signature: 'c2lnbmF0dXJlLXBpMzYz',
      capability_id: 'kyber.workforce.execute',
      reason: 'run the remediation playbook',
      ttl_minutes: 30,
    };
    const grant = await client.verifyStepUp(input);
    expect(grant.grant_id).toBe('grant_1');
    expect(grant.session?.session_id).toBe('sess_1');
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/auth/step-up/verify');
    expect(calls[0].init.method).toBe('POST');
    expect(JSON.parse(calls[0].init.body ?? '{}')).toEqual(input);
  });

  it('registers a proof key, sending the input verbatim', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: {
        data: {
          proof_key_id: 'pk_1',
          device_id: 'dev_1',
          operator_id: 'operator-1',
          algorithm: 'ES256',
          public_key: 'MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...',
          created_at: '2026-08-07T00:00:00Z',
          last_verified_at: null,
          revoked_at: null,
        },
      },
    }));
    const input = {
      device_id: 'dev_1',
      public_key: 'MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...',
      algorithm: 'ES256' as const,
      label: 'aether-mobile-ios',
    };
    const key = await client.registerProofKey(input);
    expect(key.proof_key_id).toBe('pk_1');
    expect(key.algorithm).toBe('ES256');
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/mobile/proof-keys');
    expect(calls[0].init.method).toBe('POST');
    expect(JSON.parse(calls[0].init.body ?? '{}')).toEqual(input);
  });

  it('lists proof keys, returning data.proof_keys', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: {
        data: {
          operator_id: 'operator-1',
          proof_keys: [
            {
              proof_key_id: 'pk_1',
              device_id: 'dev_1',
              operator_id: 'operator-1',
              algorithm: 'ES256',
              created_at: '2026-08-07T00:00:00Z',
              last_verified_at: null,
            },
          ],
        },
      },
    }));
    const keys = await client.listProofKeys();
    expect(keys).toHaveLength(1);
    expect(keys[0].proof_key_id).toBe('pk_1');
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/mobile/proof-keys');
    expect(calls[0].init.method).toBe('GET');
  });

  it('revokes a proof key by id (URL-encoded)', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: {
        data: {
          proof_key_id: 'pk_1',
          device_id: 'dev_1',
          operator_id: 'operator-1',
          algorithm: 'ES256',
          public_key: 'MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...',
          created_at: '2026-08-07T00:00:00Z',
          last_verified_at: null,
          revoked_at: '2026-08-07T01:00:00Z',
        },
      },
    }));
    const key = await client.revokeProofKey('pk/1');
    expect(key.revoked_at).not.toBeNull();
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/mobile/proof-keys/pk%2F1');
    expect(calls[0].init.method).toBe('DELETE');
  });

  it('lists command receipts with status and limit query params', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: { data: { commands: [], count: 0, status_filter: 'open' } },
    }));
    const list = await client.getCommandReceipts({ status: 'open', limit: 25 });
    expect(list.count).toBe(0);
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/ops/commands?status=open&limit=25');
  });

  it('omits unset command-receipt query params', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: { data: { commands: [], count: 0, status_filter: 'open' } },
    }));
    await client.getCommandReceipts();
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/ops/commands');
    await client.getCommandReceipts({ status: 'pending' });
    expect(calls[1].url).toBe('https://api.aether.test/v1/kyber/ops/commands?status=pending');
  });

  it('reads one command receipt by id (URL-encoded)', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: {
        data: {
          command: {
            command_id: 'cmd_1',
            command_type: 'remediation.playbook',
            status: 'open',
            requested_by: 'operator-1',
            session_id: 'sess_1',
            device_id: 'dev_1',
            environment: 'production',
            tenant_ids: ['tenant-1'],
            resource_ids: ['res_1'],
            reason: 'contain the blast radius',
            action_class: 4,
            dry_run: false,
            idempotency_key: 'idem-1',
            blast_radius: null,
            rollback_plan: null,
            verification_plan: ['verify.status'],
            required_approvals: 1,
            approvals: [],
            approval_mode: 'self',
            step_up_verified: false,
            policy_decision_id: 'pd_1',
            incident_id: null,
            scheduled_for: null,
            created_at: '2026-08-07T00:00:00Z',
            updated_at: '2026-08-07T00:00:00Z',
            metadata: {},
          },
          spec: {},
          execution: null,
          executions: [],
          verification: null,
          verified: false,
          generated_at: '2026-08-07T00:00:00Z',
        },
      },
    }));
    const detail = await client.getCommandReceipt('cmd_1');
    expect(detail.command.command_id).toBe('cmd_1');
    expect(detail.verification).toBeNull();
    expect(detail.verified).toBe(false);
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/ops/commands/cmd_1');
    expect(calls[0].init.method).toBe('GET');
  });
});
