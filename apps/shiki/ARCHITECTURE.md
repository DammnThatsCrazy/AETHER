# SHIKI Architecture

## Overview

SHIKI sits on top of existing Aether backend planes (REST, GraphQL, WebSocket) and provides an internal operator UI. It does not duplicate backend logic.

## Directory Structure

```
apps/shiki/
  src/
    app/          # Entry point, providers, router, error boundary
    routes/       # Route definitions and path builders
    pages/        # 8 page-level components (Mission, Live, GOUF, etc.)
    components/
      system/     # SHIKI design system primitives (Button, Card, Badge, etc.)
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
      gouf/       # Graph data hooks
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
  Switched via env: VITE_SHIKI_ENV
```

## Key Patterns

- **System components**: All third-party UI is wrapped in SHIKI-owned components
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

SHIKI uses a lightweight approach:
- Server state: Feature hooks with local state (will migrate to React Query when needed)
- UI state: React useState/useReducer at feature level
- Cross-cutting: Context providers (auth, notifications, theme)
- No global store — each feature manages its own state
