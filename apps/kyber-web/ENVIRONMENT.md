# KYBER Environment Configuration

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VITE_KYBER_ENV` | Yes | — | Runtime environment (`local`, `staging`, `production`, or `test`) |
| `VITE_API_BASE_URL` | Yes | — | Backend API base URL |
| `VITE_WS_BASE_URL` | Live modes | `ws://localhost:8000` | WebSocket base URL |
| `VITE_GRAPHQL_URL` | Live modes | `http://localhost:8000/v1/analytics/graphql` | GraphQL endpoint |
| `VITE_OIDC_AUTHORITY` | Staging/Prod | — | OIDC provider URL |
| `VITE_OIDC_CLIENT_ID` | Staging/Prod | — | OIDC client identifier |
| `VITE_OIDC_REDIRECT_URI` | Staging/Prod | — | OIDC callback URL |
| `VITE_OIDC_SCOPE` | No | `openid profile email groups` | OIDC scopes |
| `VITE_SLACK_WEBHOOK_URL` | No | — | Slack notification webhook |
| `VITE_AUTOMATION_POSTURE` | No | `conservative` | Automation posture |
| `VITE_FEATURE_FLAGS` | No | `{}` | Feature flags JSON |

## Runtime Environments

### local
- Connected to locally running Aether services
- Uses a real backend-owned session
- Never substitutes fixtures when an API is unavailable

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

On boot, KYBER validates all environment variables via Zod. Missing or invalid
required values prevent normal application startup.
