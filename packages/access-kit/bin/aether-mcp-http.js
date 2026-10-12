#!/usr/bin/env node

import { createServer } from 'node:http';
import { Readable, Writable } from 'node:stream';
import { pathToFileURL } from 'node:url';

import { createRemoteMcpFetchHandler } from '../src/mcp-http.mjs';

const MAX_HEADER_BYTES = 8 * 1024;
const SINGLETON_SECURITY_HEADERS = new Set([
  'host',
  'origin',
  'authorization',
  'x-aether-observe-key',
  'x-aether-site-id',
]);

function requestHeaders(request) {
  const headers = new Headers();
  const seen = new Set();
  for (let index = 0; index < request.rawHeaders.length; index += 2) {
    const name = request.rawHeaders[index];
    const value = request.rawHeaders[index + 1];
    const lowerName = name.toLowerCase();
    if (SINGLETON_SECURITY_HEADERS.has(lowerName)) {
      if (seen.has(lowerName)) throw new Error('ambiguous security header');
      seen.add(lowerName);
    }
    headers.append(name, value);
  }
  return headers;
}

function webRequest(request) {
  const requestTarget = request.url || '/';
  if (!requestTarget.startsWith('/') || requestTarget.startsWith('//')
      || requestTarget.includes('\\') || requestTarget.includes('#')) {
    throw new Error('invalid request target');
  }
  const url = new URL(requestTarget, 'http://access-kit.internal');
  if (url.origin !== 'http://access-kit.internal') throw new Error('invalid request target');

  const method = request.method || 'GET';
  const init = { method, headers: requestHeaders(request) };
  if (method !== 'GET' && method !== 'HEAD') {
    init.body = Readable.toWeb(request);
    init.duplex = 'half';
  }
  return new Request(url, init);
}

async function writeResponse(response, outgoing) {
  outgoing.statusCode = response.status;
  if (response.statusText) outgoing.statusMessage = response.statusText;
  for (const [name, value] of response.headers) outgoing.setHeader(name, value);
  if (!response.body) {
    outgoing.end();
    return;
  }
  await response.body.pipeTo(Writable.toWeb(outgoing));
}

export function createAccessKitHttpServer({ env = process.env } = {}) {
  const fetchHandler = createRemoteMcpFetchHandler({ env });
  const server = createServer({ maxHeaderSize: MAX_HEADER_BYTES }, async (incoming, outgoing) => {
    try {
      const response = await fetchHandler(webRequest(incoming));
      await writeResponse(response, outgoing);
    } catch (error) {
      const status = /security header|request target/.test(error?.message ?? '') ? 400 : 500;
      if (!outgoing.headersSent) {
        outgoing.statusCode = status;
        outgoing.setHeader('cache-control', 'no-store');
        outgoing.setHeader('content-type', 'application/json; charset=utf-8');
        outgoing.setHeader('x-content-type-options', 'nosniff');
        outgoing.end(JSON.stringify({ error: { code: status === 400 ? 'invalid_http_request' : 'request_failed' } }));
      } else {
        outgoing.destroy();
      }
    }
  });
  server.headersTimeout = 15_000;
  server.requestTimeout = 30_000;
  server.keepAliveTimeout = 5_000;
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const parsedPort = Number.parseInt(process.env.PORT || '8080', 10);
  if (!Number.isInteger(parsedPort) || parsedPort < 1 || parsedPort > 65_535) {
    process.stderr.write('PORT must be an integer between 1 and 65535.\n');
    process.exitCode = 1;
  } else {
    const server = createAccessKitHttpServer();
    server.once('error', () => {
      process.stderr.write('Aether Access Kit MCP HTTP server could not start.\n');
      process.exitCode = 1;
    });
    server.listen(parsedPort, process.env.HOST || '0.0.0.0');
    const close = () => server.close(() => { process.exitCode = 0; });
    process.once('SIGTERM', close);
    process.once('SIGINT', close);
  }
}
