# Website Go-Live Checklist

## What you're deploying

| URL | Host | Source |
|---|---|---|
| `olympuslabsml.com` | Squarespace | Marketing site (your Squarespace editor) |
| `www.olympuslabsml.com` | Squarespace | → redirects to apex |
| `aether.olympuslabsml.com` | AWS Amplify | `frontend/aether-marketing/` |
| `docs.olympuslabsml.com` | AWS Amplify | `frontend/docs/` |
| `app.olympuslabsml.com` | AWS Amplify | `frontend/aether/` |
| `api.olympuslabsml.com` | AWS ECS/ALB | `Backend Architecture/aether-backend/` |

## Prerequisites — gather before running

### 1. AWS Account

- [ ] AWS account created
- [ ] IAM user or SSO role with admin access (for initial setup)
- [ ] AWS CLI v2 installed and configured (`aws sts get-caller-identity` works)
- [ ] Region decided (default: `us-east-1`)

### 2. Tools

- [ ] Terraform >= 1.7 installed (`terraform version`)
- [ ] Docker installed and running (`docker info`)
- [ ] Git repo cloned with latest `main`

### 3. Auth0

- [ ] Auth0 tenant created (free tier works for start)
- [ ] Management API application created in Auth0 Dashboard
- [ ] Credentials exported (NEVER put in tfvars):
  ```bash
  export AUTH0_DOMAIN="<your-tenant>.us.auth0.com"
  export AUTH0_CLIENT_ID="<from Auth0 dashboard>"
  export AUTH0_CLIENT_SECRET="<from Auth0 dashboard>"
  ```

### 4. Domain

- [ ] `olympuslabsml.com` registered at a domain registrar
- [ ] Access to change nameservers at the registrar

### 5. Squarespace

- [ ] Squarespace site created (any plan)
- [ ] Access to Settings → Domains in Squarespace admin
- [ ] Verification code ready (Settings → Domains → DNS Settings)

### 6. GitHub

- [ ] GitHub personal access token with `repo` scope (for Amplify to pull code)
  - Create at: github.com → Settings → Developer Settings → Personal Access Tokens
  - Scope: `repo` (full control of private repositories)
  - This goes into `amplify_github_access_token` terraform variable

## Deployment profile

Start with **`production-lean`** ($187/month baseline):
- Aurora Serverless v2 (0.5–4 ACU)
- DynamoDB cache
- SNS/SQS events
- No NAT Gateway (public IP egress)
- No Redis, no Kafka, no Neptune

## Run it

```bash
# Export Auth0 credentials
export AUTH0_DOMAIN="your-tenant.us.auth0.com"
export AUTH0_CLIENT_ID="..."
export AUTH0_CLIENT_SECRET="..."

# Run from repo root
./scripts/deploy/go_live.sh --profile production-lean --region us-east-1
```

The script is interactive — it pauses at each critical step for your review
and manual actions (certificate validation, secret injection, nameserver update).

## After go-live

- [ ] Confirm SNS alert email subscription (check inbox)
- [ ] Inject secrets into Secrets Manager
- [ ] Run database migrations via ECS Exec
- [ ] Verify `GET https://api.olympuslabsml.com/v1/ready` returns 200
- [ ] Verify all Amplify apps build and serve
- [ ] Verify Squarespace marketing site loads at apex domain
- [ ] Set up CI: wire `TF_STATE_BUCKET`, `TF_LOCK_TABLE`, and OIDC role ARNs into GitHub environment secrets
