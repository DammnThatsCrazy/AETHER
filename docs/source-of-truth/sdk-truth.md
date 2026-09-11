# SDK Truth

Aether SDKs are thin observation clients.

## SDKs Do

- Capture local first-party observations.
- Attach tenant, site, app, device, session, user, and SDK metadata.
- Emit canonical event envelopes.
- Batch events.
- Retry safely.
- Spool offline when supported.
- Emit heartbeat events.
- Respect privacy and redaction controls.
- Send batches to `/v1/batch`.

## SDKs Do Not

- Own provider sync.
- Store provider credentials.
- Resolve identity globally.
- Write directly to the graph.
- Own attribution logic.
- Own financial normalization.
- Own tenant activation.
- Replace connectors.

## Required SDKs

- Web
- React
- React Native
- iOS
- Android

## Parity Rule

Every supported SDK must expose the same canonical observation concepts, even if platform-specific implementation details differ.
