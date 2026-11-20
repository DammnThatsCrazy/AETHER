import { describe, expect, it } from 'vitest';

import { captureRequestEvidence } from './request-evidence';

const RECEIVED = new Date('2026-11-19T12:00:00.000Z');

describe('captureRequestEvidence', () => {
  it('reads a Node IncomingMessage-like request', () => {
    const ev = captureRequestEvidence(
      {
        method: 'get',
        url: '/products/1?ref=x',
        headers: {
          host: 'shop.example',
          'user-agent': 'ChatGPT-User/1.0',
          signature: 'sig1=:AAAA:',
          'signature-input': 'sig1=("@authority");tag="web-bot-auth"',
          'signature-agent': '"https://chatgpt.com"',
          cookie: 'session=secret',
          authorization: 'Bearer secret',
        },
        socket: { remoteAddress: '::ffff:203.0.113.7', encrypted: true },
      },
      { receivedAt: RECEIVED },
    );
    expect(ev).toEqual({
      receivedAt: '2026-11-19T12:00:00.000Z',
      userAgent: 'ChatGPT-User/1.0',
      clientIp: '203.0.113.7',
      method: 'GET',
      authority: 'shop.example',
      path: '/products/1',
      query: 'ref=x',
      scheme: 'https',
      signature: 'sig1=:AAAA:',
      signatureInput: 'sig1=("@authority");tag="web-bot-auth"',
      signatureAgent: '"https://chatgpt.com"',
    });
  });

  it('never captures cookies, authorization or bodies', () => {
    const ev = captureRequestEvidence({
      method: 'POST',
      url: '/',
      headers: { cookie: 'c=1', authorization: 'Bearer t', host: 'a.example' },
    });
    expect(JSON.stringify(ev)).not.toMatch(/Bearer|c=1/);
  });

  it('reads a Fetch API Request', () => {
    const req = new Request('https://shop.example/a/b?x=1', {
      headers: { 'user-agent': 'GPTBot/1.2' },
    });
    const ev = captureRequestEvidence(req, { clientIp: '198.51.100.2', receivedAt: RECEIVED });
    expect(ev).toMatchObject({
      userAgent: 'GPTBot/1.2',
      clientIp: '198.51.100.2',
      method: 'GET',
      authority: 'shop.example',
      path: '/a/b',
      query: 'x=1',
      scheme: 'https',
    });
  });

  it('ignores X-Forwarded-For unless explicitly trusted', () => {
    const req = {
      method: 'GET',
      url: '/',
      headers: { 'x-forwarded-for': '1.2.3.4, 10.0.0.1' },
      socket: { remoteAddress: '10.0.0.1' },
    };
    expect(captureRequestEvidence(req).clientIp).toBe('10.0.0.1');
    expect(captureRequestEvidence(req, { trustForwardedFor: true }).clientIp).toBe('1.2.3.4');
  });

  it('never throws on unreadable input', () => {
    const ev = captureRequestEvidence({ method: 'GET', url: 'not a url', headers: { get: () => { throw new Error('x'); } } } as never, { receivedAt: RECEIVED });
    expect(ev).toEqual({ receivedAt: '2026-11-19T12:00:00.000Z' });
  });
});
