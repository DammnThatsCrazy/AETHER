import { describe, expect, it } from 'vitest';

import { captureA2aCallerIdentity, captureMcpClientIdentity, sha256Hex } from './protocol-identity';

describe('captureMcpClientIdentity', () => {
  it('marks a verified OAuth client and hashes the subject', () => {
    const ev = captureMcpClientIdentity({
      clientInfo: { name: 'claude-ai', version: '0.1.0' },
      protocolVersion: '2025-06-18',
      authInfo: { clientId: 'client_123', scopes: ['tools:read'], token: 'SECRET-TOKEN', extra: { sub: 'user-42', iss: 'https://auth.example' } },
    });
    expect(ev).toEqual({
      protocol: 'mcp',
      mcp: {
        clientInfo: { name: 'claude-ai', version: '0.1.0' },
        protocolVersion: '2025-06-18',
        oauth: {
          verified: true,
          clientId: 'client_123',
          issuer: 'https://auth.example',
          scopes: ['tools:read'],
          subjectHash: sha256Hex('user-42'),
        },
      },
    });
    expect(JSON.stringify(ev)).not.toContain('SECRET-TOKEN');
    expect(JSON.stringify(ev)).not.toContain('user-42');
  });

  it('without authInfo it is a declaration only', () => {
    const ev = captureMcpClientIdentity({ clientInfo: { name: 'cursor' } });
    expect(ev).toEqual({ protocol: 'mcp', mcp: { clientInfo: { name: 'cursor' } } });
  });
});

describe('captureA2aCallerIdentity', () => {
  it('keeps only identity fields of the Agent Card', () => {
    const ev = captureA2aCallerIdentity({
      agentCard: {
        name: 'Travel Agent', url: 'https://agent.example/a2a', version: '1.0',
        provider: { organization: 'Example Co', url: 'https://example.com' },
        skills: [{ id: 'book', description: 'long text' }],
        securitySchemes: { oauth: { type: 'oauth2' } },
      },
      agentCardUrl: 'https://agent.example/.well-known/agent-card.json',
      authenticated: true,
      cardSignatureVerified: true,
      authScheme: 'oauth2',
    });
    expect(ev).toEqual({
      protocol: 'a2a',
      a2a: {
        agentCard: {
          name: 'Travel Agent', url: 'https://agent.example/a2a', version: '1.0',
          provider: { organization: 'Example Co', url: 'https://example.com' },
        },
        agentCardUrl: 'https://agent.example/.well-known/agent-card.json',
        authenticated: true,
        cardSignatureVerified: true,
        authScheme: 'oauth2',
      },
    });
  });
});
