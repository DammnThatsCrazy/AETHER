# Aether on AWS — Setup From Zero

The single guided path from an empty AWS account to a running Aether
environment. It targets the **live, profile-driven Terraform root** at
[`terraform/`](terraform/) — not the six-account reference model in
[`README.md`](README.md), and not the [dead `environments/`
tree](terraform/README.md#dead-second-terraform-tree).

**Canonical reference:** [`docs/AWS-DEPLOYMENT.md`](../../docs/AWS-DEPLOYMENT.md)
describes the infrastructure exactly as the Terraform defines it. This file is
the *procedure*; that doc is the *reference*. When they disagree, the doc wins.

> **Current status.** No AWS account, credentials, or applied infrastructure is
> wired to this repository today (`config/deployment_readiness.yaml`, exception
> `DR-EX-NO-CLOUD-ACCOUNT`). `deployment_ready` is `false`. This guide is what it
> takes to change that. Every step below that needs credentials is, by design,
> not runnable from CI until a real account exists.

---

## Why setup takes real steps (and can't be one command)

Terraform provisions the VPC, ECS, data stores, and everything else — but four
things must exist *before* the first plan, because Terraform structurally can't
create them for itself:

1. **A remote state backend** (S3 bucket + DynamoDB lock table). `versions.tf`
   declares `backend "s3" {}` with no inline config; the backend must already
   exist to hold the state that would create it. → **Step 1**, scripted.
2. **An ACM certificate** in the target region for your domain, and a **Route 53
   hosted zone**. The ALB listener and DNS edge reference them. → **Step 2**.
3. **Auth0 tenant credentials**, supplied as environment variables (never
   tfvars — see the security note in [`terraform/README.md`](terraform/README.md)).
   → **Step 2**.
4. **Container images in ECR**, because task definitions pin an immutable image
   **digest** and every plan must supply `backend_image_digest`. ECR itself is
   created by Terraform, so the first apply is deliberately two-phase. → **Step 4**.

None of this is unusual for a production AWS footprint; it's just not
zero-config. The rest of this guide walks each piece in order.

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| AWS CLI | v2.x | Credentials for the **target account** |
| Terraform | 1.7 – 1.x | 1.7 is the effective floor (`terraform test` needs `mock_provider`); pin per `versions.tf` (`~> 1.5`) |
| Docker | any recent | To build and push the backend image |
| An AWS account | — | One account **per** production-class profile (see note in Step 3) |
| A registered domain + Route 53 hosted zone | — | For the ALB/HTTPS edge |
| An Auth0 tenant | — | SPA clients + API resource server are Terraform-managed |

Pick a **deployment profile** before you start — it decides cost and shape:

| Profile | Use for | Cache / Events / Graph | NAT |
|---|---|---|---|
| `staging` | Release rehearsal, cost-capped, sleeps when idle | DynamoDB / SQS / Postgres | none (public IP) |
| `production-lean` | Founding-tenant production, bounded bill | DynamoDB / SQS / Postgres | none (public IP) |
| `production-scale` | Scaled production | ElastiCache / MSK / Neptune | 1 NAT |
| `enterprise-isolated` | Isolated enterprise | ElastiCache / MSK / Neptune | 1 NAT per AZ |

Full matrix: [`docs/DEPLOYMENT-PROFILES.md`](../../docs/DEPLOYMENT-PROFILES.md).
**Start with `staging`.** It is the strictest rehearsal gate and the intended
first target.

---

## Step 1 — Bootstrap the Terraform state backend

Creates the S3 state bucket (versioned, encrypted, public access blocked) and
the DynamoDB lock table. Idempotent — safe to re-run.

```bash
cd "AWS Deployment/aether-aws/terraform/bootstrap"

# Preview first:
./bootstrap_state_backend.sh --dry-run \
  --bucket "aether-tfstate-$(aws sts get-caller-identity --query Account --output text)" \
  --lock-table aether-tf-locks \
  --region us-east-1

# Then for real (drop --dry-run):
./bootstrap_state_backend.sh \
  --bucket "aether-tfstate-$(aws sts get-caller-identity --query Account --output text)" \
  --lock-table aether-tf-locks \
  --region us-east-1
```

Record the bucket and table names — they become the `TF_STATE_BUCKET` and
`TF_LOCK_TABLE` values in Step 3.

---

## Step 2 — External prerequisites (cert, DNS, Auth0)

1. **ACM certificate** for your domain in the **same region** as the deployment.
   Request it (`aws acm request-certificate`) and complete DNS validation. Note
   the certificate ARN → `acm_certificate_arn`.
2. **Route 53 hosted zone** for the domain. The ALB gets a CNAME/alias here after
   apply (`terraform output alb_dns`). The DNS edge is managed **outside** this
   Terraform root by design.
3. **Auth0** tenant with a management application. Export, in the environment
   that runs Terraform (locally or as CI secrets), **never as tfvars**:

   ```bash
   export AUTH0_DOMAIN="your-tenant.us.auth0.com"
   export AUTH0_CLIENT_ID="..."
   export AUTH0_CLIENT_SECRET="..."
   ```

   The management token must carry every scope the reviewed Auth0 resources
   need; the promotion workflow fails closed if a scope is missing.

---

## Step 3 — Configure variables and CI

1. Copy the example and fill in your values:

   ```bash
   cd "AWS Deployment/aether-aws/terraform"
   cp terraform.tfvars.example terraform.tfvars   # gitignored — never commit
   $EDITOR terraform.tfvars
   ```

   At minimum set: `deployment_profile`, `domain_name`, `acm_certificate_arn`,
   `alert_email`, `aether_app_url`, `kyber_app_url`. The profile file
   (`profiles/<profile>.tfvars`) supplies the cost/shape toggles.

2. **Wire CI** for the sole apply path,
   [`.github/workflows/terraform-promote.yml`](../../.github/workflows/terraform-promote.yml).
   Per-profile GitHub environment (`staging-terraform`, `production-lean-terraform`,
   …) with these secrets/vars:

   | Name | Value |
   |---|---|
   | `TF_STATE_BUCKET` | the bucket from Step 1 |
   | `TF_LOCK_TABLE` | the lock table from Step 1 |
   | `AWS_REGION` | your region |
   | AWS OIDC role ARNs | the plan role and the `AWS_TERRAFORM_APPLY_ROLE_ARN` state-write role |

   The apply role is deliberately least-privilege; its checked-in contract is
   `config/staging_apply_iam_policy.yaml` (staging) and is verified by IAM
   policy simulation before any mutation. State access is a separate contract
   in `config/terraform_state_access_policy.yaml`.

> **Note — production-class name collisions.** `production-lean`,
> `production-scale`, and `enterprise-isolated` all inherit `environment =
> production` and therefore generate identical resource names. Separate state
> keys keep their *state* apart but not their *names*. Two production-class
> profiles **cannot** share one account/region — give each its own AWS account.
> Staging is the only profile that overrides `environment`, so it coexists
> cleanly.

---

## Step 4 — Build and push the backend image (two-phase first apply)

ECR repositories are created by Terraform, but a plan needs an image digest. So
the first apply is two phases:

**Phase A — create the registries only:**

```bash
terraform init \
  -backend-config="bucket=${TF_STATE_BUCKET}" \
  -backend-config="dynamodb_table=${TF_LOCK_TABLE}" \
  -backend-config="key=profiles/staging/terraform.tfstate" \
  -backend-config="region=${AWS_REGION}" \
  -backend-config="encrypt=true"

terraform apply -target=module.ecr -var-file=profiles/staging.tfvars
```

**Phase B — build, push, capture the digest:**

```bash
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin \
  "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"

docker build -t aether-backend ./backend   # adjust to your build context
docker tag aether-backend:latest \
  "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/aether-backend:latest"
docker push \
  "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/aether-backend:latest"

# The digest you feed into backend_image_digest (must match ^sha256:[0-9a-f]{64}$):
aws ecr describe-images --repository-name aether-backend \
  --image-ids imageTag=latest \
  --query 'imageDetails[0].imageDigest' --output text
```

The `ml_image_digest` is only required for the dedicated ML service on
`production-scale` / `enterprise-isolated`; leave it empty on lean/staging.

---

## Step 5 — Plan and apply

**Do not `terraform apply` production by hand.**
[`terraform-promote.yml`](../../.github/workflows/terraform-promote.yml) is the
**sole apply path**: it consumes an exact reviewed binary plan, re-verifies the
plan digest, profile, state key, commit, Terraform version, lockfile digest, and
24-hour expiry, and **never re-plans**. That is what makes an apply auditable.

Locally you may still produce a plan for review:

```bash
terraform plan \
  -var-file=profiles/staging.tfvars \
  -var="backend_image_digest=sha256:<digest-from-step-4>" \
  -out=tfplan
```

Then dispatch the promotion workflow for the `staging` profile with the reviewed
plan. Staging's wake/validate/sleep cadence is in
[`docs/STAGING-WAKE-SLEEP.md`](../../docs/STAGING-WAKE-SLEEP.md); the operator
procedure is [`docs/DEPLOYMENT-RUNBOOK.md`](../../docs/DEPLOYMENT-RUNBOOK.md).

---

## Step 6 — Post-deploy

1. **Confirm the SNS email subscription** sent to `alert_email` — alarms deliver
   nothing until the link is clicked.
2. **Inject secret values.** Secrets Manager stubs are created empty. Store
   **raw strings, not JSON** (ECS `valueFrom` injects the whole secret string):

   ```bash
   aws secretsmanager put-secret-value \
     --secret-id aether/jwt-secret \
     --secret-string 'REPLACE_WITH_SECURE_RANDOM_256BIT_KEY'
   ```

   `aether/db-password` is populated automatically by Aurora's managed rotation;
   `aether/redis-auth-token` exists only on Redis profiles.
3. **Run database migrations** from inside the VPC (ECS Exec, bastion, or a
   one-off Fargate task). On a `public_ip` profile (staging / lean) use the
   **public** subnets and `assignPublicIp=ENABLED` — there is no NAT to egress
   through, and a public IP in a private subnet still has no default route:

   ```bash
   terraform output public_subnet_ids   # the right subnet list
   ```
4. **Verify readiness:** `GET /v1/ready` fails unless the database alembic
   revision equals the packaged head.

---

## Tear-down

Removing applied infrastructure — including turning a backend off by flipping a
profile toggle — goes through
[`terraform/DECOMMISSION.md`](terraform/DECOMMISSION.md). **A profile change that
plans a destroy on a data store is a stop-the-line event, not a diff to skim.**

---

## Verification without an account

Everything below runs with **no AWS credentials** and is what CI enforces today:

```bash
cd "AWS Deployment/aether-aws/terraform"
terraform validate
terraform test -filter=tests/profile_plan.tftest.hcl   # per-profile planned graph

# from the repo root:
make test-terraform-profiles
make validate-cost-policy-terraform
```

## See also

- [`docs/AWS-DEPLOYMENT.md`](../../docs/AWS-DEPLOYMENT.md) — canonical infrastructure reference
- [`terraform/README.md`](terraform/README.md) — the live root, profiles, and egress modes
- [`docs/DEPLOYMENT-PROFILES.md`](../../docs/DEPLOYMENT-PROFILES.md) — the profile matrix
- [`docs/DEPLOYMENT-RUNBOOK.md`](../../docs/DEPLOYMENT-RUNBOOK.md) — operator procedure
- [`config/deployment_readiness.yaml`](../../config/deployment_readiness.yaml) — the readiness evidence gate
