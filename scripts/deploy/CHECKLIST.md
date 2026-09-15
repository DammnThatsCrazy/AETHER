# Website Go-Live Checklist

## What you're deploying

| URL | Host | Source |
|---|---|---|
| `olympuslabsml.com` | Squarespace | Apex/redirect surface → `www` |
| `www.olympuslabsml.com` | AWS Amplify | `frontend/olympus-marketing/` |
| `aether.olympuslabsml.com` | AWS Amplify | `frontend/aether-marketing/` |
| `docs.olympuslabsml.com` | AWS Amplify | `frontend/docs/` |
| `app.olympuslabsml.com` | AWS Amplify | `frontend/aether/` |
| `status.olympuslabsml.com` | AWS Amplify | `frontend/status/` |
| `kyber.olympuslabsml.com` | Internal only | No public DNS/application route by default |
| `api.olympuslabsml.com` | AWS ECS/ALB | `services/backend/` |

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
- [ ] Access to edit Squarespace DNS records (nameserver changes are not part
      of the first-release path)

### 5. Squarespace

- [ ] Squarespace domain access confirmed (an editorial site is optional; the
      first-release Olympus shell is the Amplify build)
- [ ] Access to Settings → Domains in Squarespace admin
- [ ] Ability to add the Amplify custom-domain CNAME targets from Terraform
      output

### 6. GitHub

- [ ] Create a repository-scoped GitHub token for Amplify to pull code
  - Create at: github.com → Settings → Developer Settings → Personal Access Tokens
  - Scope: the minimum repository-read access required by the private repository
  - This goes into the `amplify_github_access_token` Terraform variable
  - AWS Amplify requires this token for public and private GitHub repositories;
    the staging workflow rejects the historical `-` placeholder before AWS
    credentials are assumed

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
- [ ] Verify the Squarespace apex redirects to the Amplify-hosted
      `www.olympuslabsml.com` Olympus shell
- [ ] Set up CI: wire `TF_STATE_BUCKET`, `TF_LOCK_TABLE`, and OIDC role ARNs into GitHub environment secrets
