import { readStoredSession } from './auth.mjs';

/**
 * Make an optional OS-stored human session available to authenticated reads in
 * the local MCP process. MCP observe-only hosts must still start when no
 * keyring is configured, so credential-store failures are intentionally
 * deferred until a tenant read is invoked.
 */
export async function loadMcpStoredSession(env = process.env, readSession = readStoredSession) {
  const hasExplicitReadCredential = Boolean(
    (typeof env.AETHER_API_KEY === 'string' && env.AETHER_API_KEY.trim())
    || (typeof env.AETHER_SESSION_TOKEN === 'string' && env.AETHER_SESSION_TOKEN.trim()),
  );
  if (hasExplicitReadCredential) return false;

  try {
    const session = await readSession(env);
    if (typeof session?.token === 'string' && session.token.trim()) {
      env.AETHER_SESSION_TOKEN = session.token;
      return true;
    }
  } catch {
    // Keep stdio available to site-bound publishable-key observe workflows.
    // A later read reports its normal missing-credential/API error.
  }
  return false;
}
