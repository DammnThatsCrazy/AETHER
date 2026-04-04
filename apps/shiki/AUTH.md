# SHIKI Authentication & Authorization

## Authentication

SHIKI uses generic OIDC with Authorization Code Flow + PKCE.

### Flow
1. User clicks "Sign in with SSO"
2. SHIKI generates PKCE verifier/challenge
3. Redirects to OIDC provider's `/authorize` endpoint
4. Provider returns authorization code
5. SHIKI exchanges code for tokens via backend proxy
6. ID token claims are decoded to extract user identity and groups
7. Groups are mapped to SHIKI roles

### Local Development
In `local-mocked` and `local-live` modes, mock auth is available with a role selector UI. This is disabled in staging and production.

### Token Management
- Access tokens stored in memory only (never localStorage)
- Refresh handled via OIDC provider
- No secrets in frontend code

## Authorization (RBAC)

### Roles

| Role | Read | Approve | Intervene | Command | Diagnose | Revert | Notes | Export |
|------|------|---------|-----------|---------|----------|--------|-------|--------|
| `shiki_executive_operator` | All | Yes | Yes | No | View | Yes | Yes | Yes |
| `shiki_engineering_command` | All | Yes | Yes | Yes | Full | Yes | Yes | Yes |
| `shiki_specialist_operator` | All | Limited | No | No | View | No | Yes | No |
| `shiki_observer` | All | No | No | No | View | No | No | No |

### Action Classes

| Class | Description | Who Can Act |
|-------|-------------|------------|
| 0 | Read-only | All roles |
| 1 | Safe additive automation | Engineering, Executive |
| 2 | Moderate enrichment | Engineering, Executive, Specialist |
| 3 | Operational interventions | Engineering, Executive |
| 4 | Graph-sensitive changes | Engineering, Executive |
| 5 | Destructive / compliance / legal | Engineering only |

### Automation Postures

| Posture | Auto-approve | Requires Approval |
|---------|-------------|-------------------|
| Conservative | Class 0 only | Class 1+ |
| Balanced | Class 0-2 | Class 3+ |
| Aggressive | Class 0-3 | Class 4+ |

Production defaults to **conservative** posture.

### Action Attribution

Every action records:
- User ID, display name, email
- Role at time of action
- Timestamp and environment
- Reason/explanation
- Correlation ID
- Revert linkage (if reversible)
