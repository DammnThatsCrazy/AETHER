# Kyber Architecture

## Overview

Kyber sits on top of existing Aether backend planes (REST, GraphQL, WebSocket) and provides an internal operator UI. It does not duplicate backend logic.

## Directory Structure

```
apps/kyber/
  src/
    app/          # Entry point, providers, router, error boundary
    routes/       # Route definitions and path builders
    pages/        # 8 page-level components (Mission, Live, Noesis, etc.)
    components/
      system/     # Kyber design system primitives (Button, Card, Badge, etc.)
      layout/     # AppShell, Sidebar, TopBar, PageWrapper
      cards/      # Shared card components
      charts/     # Recharts wrappers (throughput, severity, sparklines)
      graph/      # Cytoscape.js graph canvas, inspector, toolbar, controls
      timelines/  # Event timeline and activity feed
      entities/   # Entity 360 views, list tables, score cards
      controllers/# Controller cards, roster, CHAR panel, objectives
      approvals/  # Approval modal, action class badges, revert buttons
      diagnostics/# Dependency, circuit breaker, health summary cards
      notifications/# Alert center, activity rail, review inbox, brief panel
      ascii/      # ASCII glyphs, sparklines, telemetry, signatures
    features/
      auth/       # OIDC auth provider, login, RequireAuth
      permissions/# RBAC, action classes, PermissionGate
      notifications/# Notification context, center, dispatcher
      brief/      # Command brief data hooks
      mission/    # Mission page data hooks
      live/       # Live event stream hooks
      noesis/     # Graph data hooks
      entities/   # Entity data hooks
      command/    # Command/controller data hooks
      diagnostics/# Diagnostics data hooks
      review/     # Review/approval data hooks
      lab/        # Lab/fixture data hooks
    lib/
      api/        # Centralized REST, GraphQL, WebSocket clients
      adapters/   # Mock/live adapter switching
      schemas/    # Zod schemas for API validation
      utils/      # cn, format, truncate utilities
      logging/    # Structured frontend logger
      featureFlags/# Typed feature flag system
      env/        # Environment config with Zod validation
      health/     # Startup checks
      replay/     # Event replay controller
    state/        # Lightweight store (useSyncExternalStore)
    hooks/        # Shared hooks (theme, debounce, websocket)
    fixtures/     # Deterministic mock data for all domains
    styles/       # Tailwind entry, theme tokens
    types/        # TypeScript type definitions
    test/         # Test suites (unit, component, integration, e2e)
```

## Data Flow

```
Backend APIs ─────────────────────────┐
  REST  /v1/analytics/*               │
  GQL   /v1/analytics/graphql          ├─→ Centralized Adapters ─→ Feature Hooks ─→ Pages
  WS    /v1/analytics/ws/events        │       (lib/api/)         (features/*)      (pages/*)
                                       │
Mock Fixtures (fixtures/) ─────────────┘
  Switched via env: VITE_KYBER_ENV
```

## Key Patterns

- **System components**: All third-party UI is wrapped in Kyber-owned components
- **Feature modules**: Each page has a corresponding feature module with data hooks
- **Adapter switching**: `isLocalMocked()` gates between fixture data and live API calls
- **Schema validation**: All API responses validated with Zod before entering state
- **Error boundaries**: Route-level + component-level error boundaries
- **Lazy loading**: All page routes are code-split via `React.lazy`
- **Permission gating**: Actions gated by role and action class via `PermissionGate`

## Controllers

12 controllers represent operational subsystems. They can be displayed in 3 modes:
- **Functional**: Generic descriptions (e.g., "Top Orchestrator")
- **Named**: Code names (e.g., "CHAR")
- **Expressive**: Full names (e.g., "CHAR — The Red Comet")

## State Management

Kyber uses a three-layer state model:

| Layer | Mechanism | When to use |
|---|---|---|
| **Server state** | `useQuery` / `useMutation` (`lib/query/`) | Any data fetched from the API |
| **Session state** | React Context (`AuthProvider`, `NotificationProvider`, `ThemeProvider`) | Auth, global notifications, theme |
| **Shared UI state** | `createStore` + `useStore` (`state/`) | UI state shared across unrelated components |

Do not put API responses into a shared store — keep them in the query cache via `useQuery`. This eliminates stale-cache bugs after mutations.

---

## Data-Fetching Patterns

All new feature hooks should use the query layer from `@kyber/lib/query`. This provides automatic caching, request deduplication, and polling.

### Standard query (cached, optional polling)

```ts
import { useQuery } from '@kyber/lib/query';
import { api } from '@kyber/lib/api/endpoints';

export function useDiagnosticsHealth() {
  return useQuery({
    key: 'diagnostics/health',
    fetcher: api.diagnostics.health,
    staleTime: 10_000,
    pollInterval: 30_000,
  });
}
```

Two components using the same `key` share one in-flight request and the same cached value. The cache is invalidated after `staleTime` ms.

### Conditional query

```ts
const { data } = useQuery({
  key: `entity/${id}`,
  fetcher: () => api.entities.get(id),
  enabled: id !== undefined,
});
```

### Mutation with cache invalidation

```ts
import { useMutation } from '@kyber/lib/query';

const { mutate, isLoading } = useMutation({
  mutationFn: (fingerprint: string) => api.diagnostics.resolveError(fingerprint),
  invalidateKeys: ['diagnostics/errors', 'diagnostics/report'],
  onSuccess: () => notify({ message: 'Error resolved', severity: 'info' }),
});
```

After a successful mutation, all query keys listed in `invalidateKeys` are
invalidated — subscribed `useQuery` hooks automatically re-fetch.

### Paginated list

```ts
import { usePaginatedQuery } from '@kyber/lib/query';

const { data, total, hasMore, fetchPage, fetchNext } = usePaginatedQuery(
  ({ offset, limit }) => api.agent.auditPage({ offset, limit }),
  25, // page size
);

useEffect(() => { fetchPage(0); }, [fetchPage]);
```

### WebSocket stream

```ts
import { useWebSocket } from '@kyber/hooks';

const { status } = useWebSocket({
  path: '/ws/v1/analytics/events',
  onMessage: handleEvent,
  enabled: !isLocalMocked(),
});
```

### Legacy pattern (manual useState + useEffect)

Older hooks use the manual pattern. These work but lack caching and
deduplication. Migrate incrementally using `useQuery` — don't refactor all at
once.

---

## Adding a New Feature

1. **API endpoints** — Add functions to `src/lib/api/endpoints.ts` under a new
   domain key (see "Adding a New API Domain" below).

2. **Feature hook** — Create `src/features/<domain>/use-<domain>-data.ts`:

   ```ts
   // features/campaigns/use-campaigns.ts
   import { useQuery } from '@kyber/lib/query';
   import { api } from '@kyber/lib/api/endpoints';

   export function useCampaigns() {
     return useQuery({
       key: 'campaigns/list',
       fetcher: () => api.campaigns.list({ limit: 100 }),
       staleTime: 60_000,
     });
   }
   ```

3. **Index re-export** — `src/features/<domain>/index.ts`:

   ```ts
   export { useCampaigns } from './use-campaigns';
   ```

4. **Fixtures** — Add `src/fixtures/<domain>.ts` with deterministic mock data.
   Guard behind `isLocalMocked()` in the feature hook.

5. **Components** — Create `src/components/<domain>/` for domain-specific UI.

6. **Page** — Create `src/pages/<domain>/<domain>-page.tsx` and register it in
   `src/app/router.tsx` using `lazy()` + `PageSuspense`.

---

## Adding a New API Domain

Open `src/lib/api/endpoints.ts` and add a new key to the `api` object:

```ts
export const api = {
  // ... existing domains

  campaigns: {
    list: (params?: { status?: string; limit?: number }) => {
      const qs = new URLSearchParams();
      if (params?.status) qs.set('status', params.status);
      if (params?.limit !== undefined) qs.set('limit', String(params.limit));
      return restClient
        .get(`/v1/campaigns?${qs}`, apiResponseSchema(campaignsListSchema))
        .then(r => r.data);
    },

    get: (id: string) =>
      restClient
        .get(`/v1/campaigns/${id}`, apiResponseSchema(campaignSchema))
        .then(r => r.data),
  },
};
```

**Rules:**
- Wrap every response in `apiResponseSchema(yourZodSchema)` to unwrap the backend's `{ data, status, timestamp }` envelope.
- Use `.passthrough()` on schemas that receive evolving backend responses to avoid breaking changes.
- Define inline schemas for simple shapes; move to `src/lib/schemas/` when shared across multiple endpoint functions.
- Prefer explicit query-string building over template literals with encoded params.

---

## Naming Conventions

| Item | Convention | Example |
|---|---|---|
| Components | PascalCase | `ControllerCard.tsx` |
| Hooks | `use-` prefix, kebab-case file | `use-entity-data.ts` |
| API modules | camelCase | `endpoints.ts` |
| TypeScript types/interfaces | PascalCase | `EntityType`, `MissionData` |
| Zod schemas | camelCase + `Schema` suffix | `healthCheckSchema` |
| Query cache keys | `domain/sub-key` | `'diagnostics/health'`, `'entity/abc123'` |
| Constants | `SCREAMING_SNAKE_CASE` | `DEFAULT_STALE_TIME_MS` |
| Files | kebab-case | `approval-modal.tsx` |
| Folders | kebab-case | `profile360/` |

---

## Import Conventions

Always use the `@kyber/` path alias — never relative paths crossing folder
boundaries:

```ts
// ✅ Correct
import { Button } from '@kyber/components/system';
import { useQuery } from '@kyber/lib/query';
import type { Entity } from '@kyber/types';
import { api } from '@kyber/lib/api/endpoints';

// ❌ Avoid
import { Button } from '../../components/system';
```

Within the same directory, relative imports are fine (`./cache`, `./use-query`).

---

## TypeScript Standards

- All interface/object type fields are `readonly` unless explicit mutation is needed.
- Optional fields use `?: T | undefined` (required by `exactOptionalPropertyTypes`).
- `noUncheckedIndexedAccess` is enabled — always guard array/record access:
  ```ts
  const first = items[0]; // type: T | undefined — must guard
  if (first !== undefined) { ... }
  ```
- Zod schemas belong in `lib/schemas/` or alongside their API function — not in `types/`.
- `types/` holds TypeScript interface declarations only (no runtime values).

---

## Authentication

Auth uses PKCE OIDC with in-memory token storage (never persisted to
`localStorage` in production). In `local-mocked` / `local-live` mode,
`AuthProvider` auto-grants a mock engineer user.

Access the token inside API clients via `getAccessToken()` from
`@kyber/features/auth` — never read it from context or state directly.

Role-based access is enforced via `<PermissionGate>` from
`@kyber/features/permissions`. Gate at the component level for UI affordances;
the backend enforces authorization independently.

---

## Mock vs Live Mode

`VITE_KYBER_ENV` controls the runtime:

| Value | API calls | Auth |
|---|---|---|
| `local-mocked` | Skipped — fixtures used | Auto-granted |
| `local-live` | `http://localhost:8000` via Vite proxy | Mock allowed |
| `staging` | Staging backend | Real OIDC |
| `production` | Production backend | Real OIDC |

Guard mock code with `isLocalMocked()`. For adapter-switching, use
`createAdapter(mockImpl, liveImpl)` or `createLazyAdapter(...)` from
`@kyber/lib/adapters`.

---

## Component Standards

### Design System Primitives (`components/system/`)

| Component | Use case |
|---|---|
| `Button` | All clickable actions |
| `Card` | Content grouping |
| `Badge` / `SeverityBadge` | Status labels |
| `DataTable` | Tabular data |
| `Modal` | Overlay dialogs |
| `Tabs` | Section switching |
| `LoadingState` | Skeleton placeholders |
| `ErrorState` | Error display with retry CTA |
| `EmptyState` | Empty list / no data |
| `Tooltip` | Contextual help |
| `StatusIndicator` | Live status dot |

System components must **not** import from `features/` or `lib/api/`. They
receive all data via props.

Domain-specific display logic belongs in `components/<domain>/`, not in
`components/system/`.

---

## Error Handling

The API layer normalizes all errors to `RestClientError` (code, message, status,
correlationId). Feature hooks catch these and expose `error: string | null`.

- At the page level, `PageSuspense` → `ErrorBoundary` catches render errors.
- For per-section errors, use `<ErrorState>` from the system library.
- Log with `log.error()` from `@kyber/lib/logging` — never `console.error`.

---

## Testing

| Type | Location | Runner |
|---|---|---|
| Unit (logic/utils) | `src/test/unit/` | Vitest |
| Component (RTL) | `src/test/component/` | Vitest + @testing-library/react |
| Integration (MSW) | `src/test/integration/` | Vitest + MSW |
| E2E | `src/test/e2e/` | Playwright |

Use MSW for API mocking in integration tests — do not mock `fetch` directly.
Fixture data in tests should match the fixtures in `src/fixtures/`.

---

## Environment Variables

Declared and validated in `src/lib/env/config.ts`. To add a new variable:

1. Add it to `envSchema` with a Zod type and default.
2. Add it to `.env.example` at the repo root.
3. Access it via the `env` object — never `import.meta.env` directly.

---

## Backend Integration Checklist

When wiring a new backend endpoint to the frontend:

- [ ] Add the endpoint function to `src/lib/api/endpoints.ts`
- [ ] Define a Zod response schema (inline or in `src/lib/schemas/`)
- [ ] Wrap with `apiResponseSchema(yourSchema)` to unwrap the backend envelope
- [ ] Use `.passthrough()` if the backend may add fields not yet modeled
- [ ] Add mock fixtures in `src/fixtures/<domain>.ts`
- [ ] Write a feature hook using `useQuery` or `useMutation`
- [ ] Test against `VITE_KYBER_ENV=local-live` before marking complete
