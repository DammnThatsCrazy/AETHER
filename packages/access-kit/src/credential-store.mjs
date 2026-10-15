const SERVICE_NAME = 'io.aether.access-kit';
const SESSION_ACCOUNT_PREFIX = 'human-session:';
const SESSION_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;

function validateStoredSession(session) {
  if (!session || typeof session !== 'object' || Array.isArray(session)
      || session.version !== 1
      || typeof session.token !== 'string' || !session.token.trim() || session.token.length > 8192
      || /[\u0000-\u001f\u007f]/.test(session.token)
      || typeof session.session_id !== 'string' || !SESSION_ID_PATTERN.test(session.session_id)) {
    return null;
  }
  return {
    version: 1,
    token: session.token,
    session_id: session.session_id,
  };
}

async function nativeEntry(apiOrigin) {
  try {
    const { AsyncEntry } = await import('@napi-rs/keyring');
    if (typeof AsyncEntry !== 'function') throw new Error('AsyncEntry is unavailable');
    return new AsyncEntry(
      SERVICE_NAME,
      `${SESSION_ACCOUNT_PREFIX}${apiOrigin}`,
      // Require the persistent Secret Service on Linux. The package's
      // default fallback is kernel keyutils, which does not survive reboot.
      { linux: { store: 'secret-service' } },
    );
  } catch {
    throw new Error(
      'A persistent OS credential store is unavailable. Configure macOS Keychain, Windows Credential Manager, or Linux Secret Service, then retry.',
    );
  }
}

export function createCredentialStore(entryFactory = nativeEntry) {
  async function entry(apiOrigin) {
    return entryFactory(
      apiOrigin,
      SERVICE_NAME,
      `${SESSION_ACCOUNT_PREFIX}${apiOrigin}`,
      { linux: { store: 'secret-service' } },
    );
  }

  return {
    async read(apiOrigin) {
      const keyringEntry = await entry(apiOrigin);
      let serialized;
      try {
        serialized = await keyringEntry.getPassword();
      } catch {
        throw new Error('Could not read the Aether session from the OS credential store.');
      }
      if (serialized === null || serialized === undefined || serialized === '') return null;
      let parsed;
      try {
        parsed = JSON.parse(serialized);
      } catch {
        throw new Error('The stored Aether session is unreadable; remove its OS credential-store entry and sign in again.');
      }
      const session = validateStoredSession(parsed);
      if (!session) {
        throw new Error('The stored Aether session has an invalid format; remove its OS credential-store entry and sign in again.');
      }
      return session;
    },

    async write(apiOrigin, session) {
      const value = validateStoredSession({ version: 1, ...session });
      if (!value) throw new Error('Aether returned an invalid human-session credential.');
      const keyringEntry = await entry(apiOrigin);
      try {
        await keyringEntry.setPassword(JSON.stringify(value));
      } catch {
        throw new Error('Could not save the Aether session to the OS credential store.');
      }
    },

    async remove(apiOrigin) {
      const keyringEntry = await entry(apiOrigin);
      try {
        const current = await keyringEntry.getPassword();
        if (current !== null && current !== undefined && current !== '') {
          await keyringEntry.deletePassword();
        }
      } catch {
        throw new Error('Could not remove the Aether session from the OS credential store.');
      }
    },
  };
}

export const credentialStore = createCredentialStore();
