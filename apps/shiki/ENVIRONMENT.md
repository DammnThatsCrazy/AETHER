# SHIKI Environment Configuration

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VITE_SHIKI_ENV` | Yes | `local-mocked` | Runtime environment |
| `VITE_API_BASE_URL` | Live modes | `http://localhost:8000` | Backend API base URL |
| `VITE_WS_BASE_URL` | Live modes | `ws://localhost:8000` | WebSocket base URL |
| `VITE_GRAPHQL_URL` | Live modes | `http://localhost:8000/v1/analytics/graphql` | GraphQL endpoint |
| `VITE_OIDC_AUTHORITY` | Staging/Prod | — | OIDC provider URL |
| `VITE_OIDC_CLIENT_ID` | Staging/Prod | — | OIDC client identifier |
| `VITE_OIDC_REDIRECT_URI` | Staging/Prod | — | OIDC callback URL |
| `VITE_OIDC_SCOPE` | No | `openid profile email groups` | OIDC scopes |
| `VITE_SLACK_WEBHOOK_URL` | No | — | Slack notification webhook |
| `VITE_AUTOMATION_POSTURE` | No | `conservative` | Automation posture |
| `VITE_FEATURE_FLAGS` | No | `{}` | Feature flags JSON |

## Runtime Modes

### local-mocked (default)
- All data from deterministic fixtures
- Mock auth with role selector
- No backend required
- Full app functionality

### local-live
- Connected to locally running Aether services
- Mock auth allowed
- Real API calls

### staging
- Connected to staging infrastructure
- OIDC auth required
- Real API calls

### production
- Read-only observer posture by default
- OIDC auth required
- Automation off until explicitly configured
- All actions require appropriate role and approval

## Startup Validation

On boot, SHIKI validates all environment variables via Zod. Missing required variables in staging/production will be reported on the Diagnostics page.
