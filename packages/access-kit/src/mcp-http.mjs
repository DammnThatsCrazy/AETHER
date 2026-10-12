import {
  createMcpHandler,
  isJsonContentType,
  validateHostHeader,
  validateOriginHeader,
} from '@modelcontextprotocol/server';

import { createAccessMcpServer } from '../bin/aether-mcp.js';
import { AccessApiError, getAccountContext, readApiOrigin } from './api.mjs';

export const DEFAULT_REMOTE_MCP_PATH = '/v1/access/mcp';
export const MCP_LIVENESS_PATH = '/healthz';
export const MCP_READINESS_PATH = '/readyz';
export const MAX_REMOTE_MCP_BODY_BYTES = 128 * 1024;

const API_KEY_PATTERN = /^ak_[A-Za-z0-9]{24}$/;
const SESSION_TOKEN_PATTERN = /^sess_[a-f0-9]{48}$/;
const PUBLISHABLE_KEY_PATTERN = /^pk_[a-f0-9]{24}$/;
const SITE_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;
const MCP_ALLOWED_CORS_HEADERS = [
  'authorization',
  'content-type',
  'accept',
  'mcp-protocol-version',
  'mcp-method',
  'mcp-name',
  'x-aether-observe-key',
  'x-aether-site-id',
];

function splitList(value) {
  if (typeof value !== 'string' || !value.trim()) return [];
  return value.split(',').map((item) => item.trim()).filter(Boolean);
}

function isLoopback(hostname) {
  const value = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  return value === 'localhost' || value === '127.0.0.1' || value === '::1';
}

function parseAllowedHostnames(value) {
  const hosts = splitList(value);
  if (hosts.length === 0) throw new Error('AETHER_MCP_ALLOWED_HOSTS must list at least one exact hostname.');
  const normalized = [];
  for (const host of hosts) {
    if (host.includes('*') || /[\s/@?#]/.test(host)) {
      throw new Error('AETHER_MCP_ALLOWED_HOSTS must contain exact hostnames without schemes, ports, or paths.');
    }
    let parsed;
    try {
      parsed = new URL(`http://${host}`);
    } catch {
      throw new Error('AETHER_MCP_ALLOWED_HOSTS contains an invalid hostname.');
    }
    if (parsed.hostname.toLowerCase() !== host.toLowerCase() || parsed.port || parsed.pathname !== '/') {
      throw new Error('AETHER_MCP_ALLOWED_HOSTS must contain exact hostnames without schemes, ports, or paths.');
    }
    normalized.push(parsed.hostname.toLowerCase());
  }
  return [...new Set(normalized)];
}

function parseAllowedOrigins(value) {
  const origins = splitList(value);
  const normalized = [];
  const hostnames = [];
  for (const origin of origins) {
    let parsed;
    try {
      parsed = new URL(origin);
    } catch {
      throw new Error('AETHER_MCP_ALLOWED_ORIGINS contains an invalid origin.');
    }
    if (!['https:', 'http:'].includes(parsed.protocol)
        || parsed.username || parsed.password || parsed.search || parsed.hash
        || !['', '/'].includes(parsed.pathname)
        || (parsed.protocol !== 'https:' && !isLoopback(parsed.hostname))) {
      throw new Error('AETHER_MCP_ALLOWED_ORIGINS must contain HTTPS origins (HTTP is limited to loopback development).');
    }
    normalized.push(parsed.origin);
    hostnames.push(parsed.hostname.toLowerCase());
  }
  return { origins: [...new Set(normalized)], hostnames: [...new Set(hostnames)] };
}

function parseMcpPath(value) {
  const path = value || DEFAULT_REMOTE_MCP_PATH;
  if (typeof path !== 'string' || !/^\/[A-Za-z0-9/_-]{1,127}$/.test(path)
      || path.startsWith('//') || path.endsWith('/') || path.includes('//')) {
    throw new Error('AETHER_MCP_PATH must be a bounded absolute path without a trailing slash or repeated slash.');
  }
  return path;
}

export function readRemoteMcpConfig(env = process.env) {
  return {
    apiOrigin: readApiOrigin(env),
    path: parseMcpPath(env.AETHER_MCP_PATH),
    allowedHostnames: parseAllowedHostnames(env.AETHER_MCP_ALLOWED_HOSTS),
    ...parseAllowedOrigins(env.AETHER_MCP_ALLOWED_ORIGINS),
  };
}

function jsonResponse(status, code, { requestId, origin } = {}) {
  const headers = new Headers({
    'cache-control': 'no-store',
    'content-type': 'application/json; charset=utf-8',
    'x-content-type-options': 'nosniff',
  });
  if (requestId) headers.set('x-request-id', requestId);
  if (origin) {
    headers.set('access-control-allow-origin', origin);
    headers.set('vary', 'Origin');
  }
  return new Response(JSON.stringify({ error: { code } }), { status, headers });
}

function successfulHealth(status, data) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'cache-control': 'no-store',
      'content-type': 'application/json; charset=utf-8',
      'x-content-type-options': 'nosniff',
    },
  });
}

function readBearer(request) {
  const header = request.headers.get('authorization');
  if (!header || header.length > 80) return null;
  const match = /^Bearer (.+)$/i.exec(header);
  if (!match) return null;
  const token = match[1];
  if (API_KEY_PATTERN.test(token)) return { kind: 'api_key', token };
  if (SESSION_TOKEN_PATTERN.test(token)) return { kind: 'session', token };
  return null;
}

function buildTenantEnv(apiOrigin, credential, observe) {
  const env = {
    AETHER_API_URL: apiOrigin,
    ...(credential.kind === 'api_key'
      ? { AETHER_API_KEY: credential.token }
      : { AETHER_SESSION_TOKEN: credential.token }),
  };
  if (observe) {
    env.AETHER_PUBLISHABLE_KEY = observe.key;
    env.AETHER_SITE_ID = observe.siteId;
  }
  return env;
}

function readObserveHeaders(request) {
  const key = request.headers.get('x-aether-observe-key');
  const siteId = request.headers.get('x-aether-site-id');
  if (key === null && siteId === null) return { observe: null };
  if (key === null || siteId === null
      || !PUBLISHABLE_KEY_PATTERN.test(key)
      || !SITE_ID_PATTERN.test(siteId)) {
    return { error: 'observe_credentials_invalid' };
  }
  return { observe: { key, siteId } };
}

function authFailure(error) {
  if (!(error instanceof AccessApiError)) return { status: 503, code: 'aether_api_unavailable' };
  if (error.status === 401) return { status: 401, code: 'aether_credential_rejected' };
  if (error.status === 403) return { status: 403, code: 'aether_permission_denied' };
  if (error.status === undefined || error.status >= 500) return { status: 503, code: 'aether_api_unavailable' };
  return { status: 502, code: 'aether_api_error' };
}

function corsResponse(response, origin) {
  const headers = new Headers(response.headers);
  headers.set('cache-control', 'no-store');
  headers.set('x-content-type-options', 'nosniff');
  if (origin) {
    headers.set('access-control-allow-origin', origin);
    headers.set('vary', 'Origin');
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function checkHostAndOrigin(request, config) {
  const hostResult = validateHostHeader(request.headers.get('host'), config.allowedHostnames);
  if (!hostResult.ok) return { error: 'host_not_allowed' };

  const origin = request.headers.get('origin');
  if (origin === null) return { origin: null };
  const originResult = validateOriginHeader(origin, config.hostnames);
  if (!originResult.ok || !config.origins.includes(origin)) return { error: 'origin_not_allowed' };
  return { origin };
}

function preflightResponse(request, origin) {
  if (request.headers.get('access-control-request-method')?.toUpperCase() !== 'POST') {
    return jsonResponse(403, 'cors_method_not_allowed');
  }
  const requested = request.headers.get('access-control-request-headers')
    ?.split(',').map((header) => header.trim().toLowerCase()).filter(Boolean) ?? [];
  if (requested.some((header) => !MCP_ALLOWED_CORS_HEADERS.includes(header))) {
    return jsonResponse(403, 'cors_header_not_allowed', { origin });
  }
  return new Response(null, {
    status: 204,
    headers: {
      'access-control-allow-origin': origin,
      'access-control-allow-methods': 'POST, OPTIONS',
      'access-control-allow-headers': MCP_ALLOWED_CORS_HEADERS.join(', '),
      'access-control-max-age': '600',
      'cache-control': 'no-store',
      'vary': 'Origin',
    },
  });
}

export function createRemoteMcpFetchHandler({ env = process.env } = {}) {
  return async function handleRemoteMcp(request) {
    const url = new URL(request.url);
    if (url.pathname === MCP_LIVENESS_PATH) {
      if (request.method !== 'GET') return jsonResponse(405, 'method_not_allowed');
      return successfulHealth(200, { status: 'ok' });
    }
    if (url.pathname === MCP_READINESS_PATH) {
      if (request.method !== 'GET') return jsonResponse(405, 'method_not_allowed');
      try {
        const config = readRemoteMcpConfig(env);
        return successfulHealth(200, { status: 'ready', path: config.path });
      } catch {
        return jsonResponse(503, 'configuration_not_ready');
      }
    }

    let config;
    try {
      config = readRemoteMcpConfig(env);
    } catch {
      return jsonResponse(503, 'configuration_not_ready');
    }
    if (url.pathname !== config.path || url.search || url.hash) return jsonResponse(404, 'not_found');

    const access = checkHostAndOrigin(request, config);
    if (access.error) return jsonResponse(403, access.error);
    if (request.method === 'OPTIONS') return preflightResponse(request, access.origin);
    if (request.method !== 'POST') {
      const response = jsonResponse(405, 'method_not_allowed', { origin: access.origin });
      response.headers.set('allow', 'POST, OPTIONS');
      return response;
    }
    if (!isJsonContentType(request.headers.get('content-type'))) {
      return jsonResponse(415, 'application_json_required', { origin: access.origin });
    }

    const credential = readBearer(request);
    if (!credential) return jsonResponse(401, 'aether_bearer_required', { origin: access.origin });

    const tenantEnv = buildTenantEnv(config.apiOrigin, credential, null);
    try {
      // Validate on every MCP protocol request. The API remains the source of
      // truth for credential validity, current tenant membership, and grants.
      await getAccountContext(tenantEnv);
    } catch (error) {
      const failure = authFailure(error);
      return jsonResponse(failure.status, failure.code, {
        requestId: error?.requestId,
        origin: access.origin,
      });
    }

    const observeInput = readObserveHeaders(request);
    if (observeInput.error) return jsonResponse(400, observeInput.error, { origin: access.origin });
    const requestEnv = buildTenantEnv(config.apiOrigin, credential, observeInput.observe);

    const handler = createMcpHandler(
      () => createAccessMcpServer(requestEnv, {
        includeObserve: Boolean(observeInput.observe),
        surface: 'mcp_http',
      }),
      {
        legacy: 'reject',
        keepAliveMs: 0,
        maxRequestBodySize: MAX_REMOTE_MCP_BODY_BYTES,
      },
    );
    try {
      return corsResponse(await handler.fetch(request), access.origin);
    } finally {
      await handler.close();
    }
  };
}
