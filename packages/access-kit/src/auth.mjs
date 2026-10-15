import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { normalizeInteractionOutcome } from './interaction.mjs';
import { readApiOrigin, revokeSession } from './api.mjs';
import { credentialStore } from './credential-store.mjs';

const DEVICE_GRANT = 'urn:ietf:params:oauth:grant-type:device_code';
const REQUEST_TIMEOUT_MS = 15_000;
const MAX_AUTH_RESPONSE_BYTES = 128 * 1024;
const MAX_DEVICE_TTL_SECONDS = 30 * 60;
const MAX_POLL_INTERVAL_SECONDS = 60;
const SAFE_CODE = /^[A-Za-z0-9_-]{1,64}$/;

export class AccessAuthError extends Error {
  constructor(message, { status, code, requestId, apiRequestId, interaction } = {}) {
    super(message);
    this.name = 'AccessAuthError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.apiRequestId = apiRequestId;
    this.interaction = interaction;
  }
}

function readAuth0Config(env) {
  const rawDomain = typeof env.AETHER_AUTH0_DOMAIN === 'string'
    ? env.AETHER_AUTH0_DOMAIN.trim()
    : '';
  const clientId = typeof env.AETHER_AUTH0_CLIENT_ID === 'string'
    ? env.AETHER_AUTH0_CLIENT_ID.trim()
    : '';
  const audience = typeof env.AETHER_AUTH0_AUDIENCE === 'string'
    ? env.AETHER_AUTH0_AUDIENCE.trim()
    : '';
  if (!rawDomain || !clientId || !audience) {
    throw new Error(
      'Set AETHER_AUTH0_DOMAIN, AETHER_AUTH0_CLIENT_ID, and AETHER_AUTH0_AUDIENCE from the Aether CLI Auth0 Native application configuration.',
    );
  }

  let domainUrl;
  try {
    domainUrl = new URL(rawDomain.includes('://') ? rawDomain : `https://${rawDomain}`);
  } catch {
    throw new Error('AETHER_AUTH0_DOMAIN must be an Auth0 HTTPS domain.');
  }
  if (domainUrl.protocol !== 'https:' || domainUrl.username || domainUrl.password
      || domainUrl.search || domainUrl.hash || !['', '/'].includes(domainUrl.pathname)
      || domainUrl.port) {
    throw new Error('AETHER_AUTH0_DOMAIN must be an HTTPS origin without credentials, port, path, query, or fragment.');
  }
  if (clientId.length > 256 || /[\u0000-\u0020\u007f]/.test(clientId)
      || audience.length > 512 || /[\u0000-\u0020\u007f]/.test(audience)) {
    throw new Error('AETHER_AUTH0_CLIENT_ID and AETHER_AUTH0_AUDIENCE must be bounded, non-empty values.');
  }
  return { auth0Origin: domainUrl.origin, clientId, audience };
}

async function readJson(response, source) {
  let serialized;
  try {
    serialized = await response.text();
  } catch {
    throw new Error(`${source} returned an unreadable response.`);
  }
  if (Buffer.byteLength(serialized, 'utf8') > MAX_AUTH_RESPONSE_BYTES) {
    throw new Error(`${source} returned an oversized response.`);
  }
  try {
    return JSON.parse(serialized);
  } catch {
    throw new Error(`${source} returned a non-JSON response (HTTP ${response.status}).`);
  }
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function correlationFrom(response, payload, fallback) {
  return response.headers.get('x-correlation-id')
    || response.headers.get('x-request-id')
    || (typeof payload?.meta?.request_id === 'string' ? payload.meta.request_id : null)
    || fallback;
}

function safeErrorCode(value) {
  return typeof value === 'string' && SAFE_CODE.test(value) ? value : undefined;
}

async function preflightSessionAuth(apiOrigin, fetchImpl) {
  const correlationId = randomUUID();
  let response;
  try {
    response = await fetchImpl(new URL('/v1/auth/sso/providers', `${apiOrigin}/`), {
      method: 'GET',
      redirect: 'error',
      headers: { accept: 'application/json', 'x-correlation-id': correlationId },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch {
    throw new AccessAuthError('Could not check Aether session sign-in support.', {
      requestId: correlationId,
      interaction: normalizeInteractionOutcome({ operation: 'auth', requestId: correlationId }),
    });
  }
  const payload = await readJson(response, 'Aether API');
  const requestId = correlationFrom(response, payload, correlationId);
  const apiRequestId = typeof payload?.meta?.request_id === 'string'
    ? payload.meta.request_id
    : undefined;
  if (!response.ok) {
    const code = safeErrorCode(payload?.error?.code ?? payload?.code);
    throw new AccessAuthError(
      `Aether session sign-in preflight failed (HTTP ${response.status}${code ? `, ${code}` : ''}).`,
      {
        status: response.status, code, requestId, apiRequestId,
        interaction: normalizeInteractionOutcome({
          operation: 'auth', httpStatus: response.status, requestId, apiRequestId,
          responseOk: false, code,
        }),
      },
    );
  }
  if (!isObject(payload) || !isObject(payload.data)
      || payload.data.session_auth_enabled !== true) {
    throw new AccessAuthError(
      'This Aether API does not advertise revocable human-session sign-in. Update the API before using `aether auth login`; no login credential was exchanged.',
      {
        status: response.status, requestId, apiRequestId,
        interaction: normalizeInteractionOutcome({
          operation: 'auth', httpStatus: response.status, requestId, apiRequestId,
          responseOk: true, contractError: true,
        }),
      },
    );
  }
  return { requestId, apiRequestId };
}

async function auth0Json(fetchImpl, url, body) {
  let response;
  try {
    response = await fetchImpl(url, {
      method: 'POST',
      redirect: 'error',
      headers: { accept: 'application/json', 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(body),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch {
    throw new Error('Could not reach the configured Auth0 domain.');
  }
  const payload = await readJson(response, 'Auth0');
  if (!response.ok) {
    const code = safeErrorCode(payload?.error);
    throw new Error(`Auth0 device authorization failed (HTTP ${response.status}${code ? `, ${code}` : ''}).`);
  }
  if (!isObject(payload)) throw new Error('Auth0 returned an unexpected response.');
  return payload;
}

function checkedActivationUrls(auth0Origin, payload) {
  if (typeof payload.verification_uri !== 'string' || payload.verification_uri.length > 2048
      || typeof payload.user_code !== 'string' || payload.user_code.length > 64
      || typeof payload.device_code !== 'string' || !payload.device_code.trim()
      || payload.device_code.length > 8192) {
    throw new Error('Auth0 returned an invalid device authorization response.');
  }
  const verificationUri = new URL(payload.verification_uri);
  if (verificationUri.origin !== auth0Origin || verificationUri.protocol !== 'https:') {
    throw new Error('Auth0 returned an activation URL outside the configured domain.');
  }
  let completeUri = verificationUri;
  if (typeof payload.verification_uri_complete === 'string') {
    if (payload.verification_uri_complete.length > 2048) {
      throw new Error('Auth0 returned an invalid activation URL.');
    }
    completeUri = new URL(payload.verification_uri_complete);
    if (completeUri.origin !== auth0Origin || completeUri.protocol !== 'https:') {
      throw new Error('Auth0 returned an activation URL outside the configured domain.');
    }
  }
  const expiresIn = payload.expires_in;
  const interval = payload.interval ?? 5;
  if (!Number.isSafeInteger(expiresIn) || expiresIn < 1 || expiresIn > MAX_DEVICE_TTL_SECONDS
      || !Number.isSafeInteger(interval) || interval < 1 || interval > MAX_POLL_INTERVAL_SECONDS) {
    throw new Error('Auth0 returned invalid device authorization timing values.');
  }
  return {
    deviceCode: payload.device_code,
    userCode: payload.user_code,
    verificationUri: verificationUri.toString(),
    activationUri: completeUri.toString(),
    expiresIn,
    interval,
  };
}

export async function openSystemBrowser(url) {
  const commands = process.platform === 'darwin'
    ? ['open', [url]]
    : process.platform === 'win32'
      ? ['rundll32.exe', ['url.dll,FileProtocolHandler', url]]
      : ['xdg-open', [url]];
  await new Promise((resolve, reject) => {
    const child = spawn(commands[0], commands[1], {
      detached: true,
      stdio: 'ignore',
      shell: false,
    });
    child.once('error', reject);
    child.once('spawn', resolve);
    child.unref();
  });
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function pollForAccessToken({
  auth0Origin,
  clientId,
  deviceCode,
  interval,
  expiresIn,
  fetchImpl,
  waitImpl,
  now,
}) {
  const deadline = now() + expiresIn * 1000;
  let delaySeconds = interval;
  while (now() + delaySeconds * 1000 <= deadline) {
    await waitImpl(delaySeconds * 1000);
    if (now() >= deadline) break;
    const poll = await fetchImpl(new URL('/oauth/token', `${auth0Origin}/`), {
      method: 'POST',
      redirect: 'error',
      headers: { accept: 'application/json', 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: DEVICE_GRANT,
        device_code: deviceCode,
        client_id: clientId,
      }),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    }).catch(() => {
      throw new Error('Could not reach Auth0 while waiting for device authorization.');
    });
    const payload = await readJson(poll, 'Auth0');
    if (poll.ok && isObject(payload) && typeof payload.access_token === 'string'
        && payload.access_token.length > 0 && payload.access_token.length <= 8192) {
      return payload.access_token;
    }
    const code = safeErrorCode(payload?.error);
    if (code === 'authorization_pending') continue;
    if (code === 'slow_down') {
      if (delaySeconds >= MAX_POLL_INTERVAL_SECONDS) {
        throw new Error('Auth0 requested a polling pause longer than the supported device authorization window.');
      }
      delaySeconds = Math.min(MAX_POLL_INTERVAL_SECONDS, delaySeconds + 5);
      continue;
    }
    if (code === 'access_denied') throw new Error('Auth0 device authorization was denied.');
    if (code === 'expired_token' || code === 'invalid_grant') {
      throw new Error('The Auth0 device authorization expired. Start `aether auth login` again.');
    }
    throw new Error(`Auth0 device authorization failed (HTTP ${poll.status}${code ? `, ${code}` : ''}).`);
  }
  throw new Error('The Auth0 device authorization expired. Start `aether auth login` again.');
}

async function exchangeAetherSession(apiOrigin, auth0AccessToken, fetchImpl) {
  const correlationId = randomUUID();
  let response;
  try {
    response = await fetchImpl(new URL('/v1/auth/sso/callback', `${apiOrigin}/`), {
      method: 'POST',
      redirect: 'error',
      headers: {
        accept: 'application/json',
        'content-type': 'application/json',
        'x-correlation-id': correlationId,
      },
      body: JSON.stringify({ token: auth0AccessToken, session_required: true }),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch {
    throw new AccessAuthError('Could not exchange the Auth0 identity for an Aether session.', {
      requestId: correlationId,
      interaction: normalizeInteractionOutcome({ operation: 'auth', requestId: correlationId }),
    });
  }
  const payload = await readJson(response, 'Aether API');
  const requestId = correlationFrom(response, payload, correlationId);
  const apiRequestId = typeof payload?.meta?.request_id === 'string'
    ? payload.meta.request_id
    : undefined;
  if (!response.ok) {
    const code = safeErrorCode(payload?.error?.code ?? payload?.code);
    throw new AccessAuthError(
      `Aether session exchange failed (HTTP ${response.status}${code ? `, ${code}` : ''}).`,
      {
        status: response.status, code, requestId, apiRequestId,
        interaction: normalizeInteractionOutcome({
          operation: 'auth', httpStatus: response.status, requestId, apiRequestId,
          responseOk: false, code,
        }),
      },
    );
  }
  if (!isObject(payload) || !isObject(payload.data)) {
    throw new AccessAuthError('Aether API returned an unexpected session response.', {
      status: response.status, requestId, apiRequestId,
      interaction: normalizeInteractionOutcome({
        operation: 'auth', httpStatus: response.status, requestId, apiRequestId,
        responseOk: true, contractError: true,
      }),
    });
  }
  if (typeof payload.data.api_key === 'string') {
    throw new AccessAuthError(
      'Aether returned a legacy reusable API key; the CLI refused to store or display it. Update the backend session-required SSO contract.',
      {
        status: response.status, requestId, apiRequestId,
        interaction: normalizeInteractionOutcome({
          operation: 'auth', httpStatus: response.status, requestId, apiRequestId,
          responseOk: true, contractError: true,
        }),
      },
    );
  }
  const session = payload.data.session;
  if (!isObject(session) || typeof session.token !== 'string' || !session.token.trim()
      || typeof session.session_id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(session.session_id)
      || session.credential_class !== 'human_session') {
    throw new AccessAuthError('Aether did not return a revocable human session; the CLI refused to store it.', {
      status: response.status, requestId, apiRequestId,
      interaction: normalizeInteractionOutcome({
        operation: 'auth', httpStatus: response.status, requestId, apiRequestId,
        responseOk: true, contractError: true,
      }),
    });
  }
  return {
    session: {
      token: session.token,
      session_id: session.session_id,
      credential_class: session.credential_class,
      idle_expires_at: session.idle_expires_at,
      absolute_expires_at: session.absolute_expires_at,
    },
    requestId,
    apiRequestId,
    interaction: normalizeInteractionOutcome({
      operation: 'auth', httpStatus: response.status, requestId, apiRequestId,
      responseOk: true, data: { session_id: session.session_id },
    }),
  };
}

async function revokeUnstoredSession(apiOrigin, session, fetchImpl) {
  try {
    const response = await fetchImpl(new URL(`/v1/me/sessions/${encodeURIComponent(session.session_id)}`, `${apiOrigin}/`), {
      method: 'DELETE',
      redirect: 'error',
      headers: { accept: 'application/json', 'x-session-token': session.token },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    const payload = await readJson(response, 'Aether API');
    return response.ok && payload?.data?.revoked === true;
  } catch {
    return false;
  }
}

export async function loginWithAuth0Device({
  env = process.env,
  fetchImpl = fetch,
  waitImpl = delay,
  now = Date.now,
  openBrowser = openSystemBrowser,
  onInstructions = () => {},
  store = credentialStore,
}) {
  const { auth0Origin, clientId, audience } = readAuth0Config(env);
  const apiOrigin = readApiOrigin(env);
  // Probe native store availability before asking Auth0 to create an
  // identity token or Aether to create a session.
  const existingSession = await store.read(apiOrigin);
  if (existingSession) {
    throw new Error('An Aether human session is already stored. Run `aether auth logout` before starting another login.');
  }
  const preflight = await preflightSessionAuth(apiOrigin, fetchImpl);
  const devicePayload = await auth0Json(fetchImpl, new URL('/oauth/device/code', `${auth0Origin}/`), {
    client_id: clientId,
    audience,
    scope: 'openid profile email',
  });
  const device = checkedActivationUrls(auth0Origin, devicePayload);
  onInstructions({ verificationUri: device.verificationUri, activationUri: device.activationUri, userCode: device.userCode });
  try {
    await openBrowser(device.activationUri);
  } catch {
    // The user can always follow the printed Auth0 activation URL manually.
  }
  const auth0AccessToken = await pollForAccessToken({
    auth0Origin, clientId, deviceCode: device.deviceCode, interval: device.interval,
    expiresIn: device.expiresIn, fetchImpl, waitImpl, now,
  });
  const issued = await exchangeAetherSession(apiOrigin, auth0AccessToken, fetchImpl);
  try {
    await store.write(apiOrigin, issued.session);
  } catch (error) {
    try {
      await store.remove(apiOrigin);
    } catch {
      // A failed keyring write may still have committed before reporting an
      // error. Continue with the server-side revocation even if cleanup fails.
    }
    const revoked = await revokeUnstoredSession(apiOrigin, issued.session, fetchImpl);
    throw new Error(
      `Could not store the Aether session in the OS credential store; the CLI ${revoked ? 'revoked the new session' : 'could not confirm revocation of the new session'}. ${error.message}`,
    );
  }
  return {
    session_id: issued.session.session_id,
    credential_class: issued.session.credential_class,
    idle_expires_at: issued.session.idle_expires_at ?? null,
    absolute_expires_at: issued.session.absolute_expires_at ?? null,
    requestId: issued.requestId,
    apiRequestId: issued.apiRequestId,
    interaction: issued.interaction,
    preflightRequestId: preflight.requestId,
  };
}

export async function readStoredSession(env = process.env, store = credentialStore) {
  const hasExplicitCredential = Boolean(
    (typeof env.AETHER_API_KEY === 'string' && env.AETHER_API_KEY.trim())
    || (typeof env.AETHER_SESSION_TOKEN === 'string' && env.AETHER_SESSION_TOKEN.trim()),
  );
  if (hasExplicitCredential) return null;
  const apiOrigin = readApiOrigin(env);
  return store.read(apiOrigin);
}

export async function logoutStoredSession({
  env = process.env,
  store = credentialStore,
  revoke = revokeSession,
} = {}) {
  const apiOrigin = readApiOrigin(env);
  const session = await store.read(apiOrigin);
  if (!session) throw new Error('No Aether session is stored in the OS credential store.');
  let result;
  try {
    result = await revoke(session.session_id, {
      ...env,
      AETHER_API_KEY: '',
      AETHER_SESSION_TOKEN: session.token,
    });
  } catch (error) {
    if (error?.status === 401 || error?.status === 404) await store.remove(apiOrigin);
    throw error;
  }
  await store.remove(apiOrigin);
  return result;
}
