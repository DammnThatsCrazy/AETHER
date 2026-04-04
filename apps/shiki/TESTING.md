# SHIKI Testing

## Test Stack

- **Unit tests**: Vitest — utilities, schemas, permissions, formatters
- **Component tests**: Vitest + Testing Library — cards, panels, states
- **Integration tests**: Vitest — auth flow, adapters, notification routing
- **E2E smoke**: Playwright — app boot, page navigation, key flows

## Running Tests

```bash
# Unit tests
npm run test

# Component tests
npm run test:component

# Integration tests
npm run test:integration

# E2E smoke (requires dev server)
npm run test:e2e

# All tests
npm run test:all
```

## Test Organization

```
src/test/
  setup.ts              # Test setup (jest-dom)
  unit/                 # Pure function tests
    utils.test.ts       # Format, cn utilities
    permissions.test.ts # RBAC logic
    schemas.test.ts     # Zod schema validation
    notifications.test.ts # Routing, throttle, dedup
    action-class.test.ts # Action classification
  component/            # Component render tests
    system.test.tsx     # System components
    mission.test.tsx    # Mission page
    diagnostics.test.tsx # Diagnostics page
    review.test.tsx     # Review page
  integration/          # Multi-module tests
    auth.test.tsx       # Auth boot flow
    adapters.test.ts    # REST/GQL/WS adapters
    notification-dispatch.test.ts
  e2e/                  # Playwright specs
    smoke.spec.ts       # Full app smoke test
```

## Coverage Expectations

- Utilities: >90%
- Permission logic: >95%
- Schema validation: >90%
- Component states: All loading/empty/error/permission states
- Critical flows: Auth, review approve/reject, notification dispatch

## CI Integration

Tests run as part of the repo's GitHub Actions CI pipeline. The SHIKI job runs:
1. Install dependencies
2. Lint check
3. Format check
4. TypeScript check
5. Unit tests
6. Component/integration tests
7. Production build
8. Playwright smoke tests
