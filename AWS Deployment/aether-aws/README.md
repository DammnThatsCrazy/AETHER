# tfmcp — Terraform MCP Server for Aether

Deploys [tfmcp](https://github.com/nwiizo/tfmcp) (v0.2.2) as an ECS Fargate service in Aether's AWS account, serving the MCP protocol over Streamable HTTP. Lets Aether's agentic workflow (Claude Code, Codex, Cursor) manage infrastructure via natural language — plan, apply, state inspection — with profile-awareness, IAM scoping, and CloudWatch audit logging.

## What it is

A Terraform MCP server that:
- Runs `terraform plan / apply / state` against Aether's own Terraform state backend (S3 + DynamoDB)
- Is profile-aware — knows what infrastructure exists per deployment profile (lean/scale/enterprise)
- Is IAM-scoped — can read infra for planning, can manage infra within the profile's resource set, cannot manage IAM/orgs/billing
- Is CloudWatch-logged — every operation is audited
- Is deployed via Aether's existing Terraform — one `terraform apply`, same modules, same VPC/cluster/ALB, same tagging

## Quick start

> **Prerequisite:** the tfmcp image must be built and pushed to ECR, and the digest pinned in your profile tfvars, before any apply. See [Step 1](#step-1-build-the-image) below.

### Step 1 — Build the image

```bash
# From the repository root:
AWS_ACCOUNT=123456789012 AWS_REGION=us-east-1 \
  ./AWS\ Deployment/aether-aws/build-tfmcp.sh
```

Note the sha256 digest output — pin it in your profile tfvars.

### Step 2 — Pin the image digest

In `profiles/production-lean.tfvars` (or the profile you're targeting):

```hcl
enable_tfmcp_in_lean = true
tfmcp_image_digest    = "sha256:abc123def456..."
```

### Step 3 — Plan and apply

**Do not `terraform apply` production by hand.** The reviewed promotion workflow
([`.github/workflows/terraform-promote.yml`](../../.github/workflows/terraform-promote.yml))
is the **sole apply path** for production-class profiles — it consumes an exact
reviewed binary plan, re-verifies the plan digest, profile, state key, commit,
Terraform version, lockfile digest, and 24-hour expiry, and never re-plans.

For review or staging, produce a plan locally:

```bash
cd terraform

terraform init

# Production-lean: pass only the lean tfvars — not staging + lean
terraform plan \
  -var-file=profiles/production-lean.tfvars \
  -out=tfplan
```

Then dispatch the promotion workflow (`action: plan` first, then `action: apply`
with the approved plan checksum) for the `production-lean` profile.

> **Pre-apply note for first-time tfmcp deployment.** The module references
> `var.terraform_state_bucket`, `var.terraform_lock_table`, and
> `var.terraform_state_kms_key_arn` in the task IAM policy. These must be set
> in the profile tfvars or root `terraform.tfvars` before the plan — they are
> the S3 bucket, DynamoDB lock table, and (optional) KMS key ARN for Aether's
> Terraform state backend. If they are empty, the plan fails validation.

### Step 4 — Configure MCP clients

After apply, retrieve the endpoint and auth token:

```bash
cd terraform

# Endpoint
terraform output -raw mcp_endpoint_url

# Auth token ARN, then read the secret
TFMCP_AUTH_ARN=$(terraform output -raw mcp_auth_token_secret_arn)
aws secretsmanager get-secret-value \
  --secret-id "$TFMCP_AUTH_ARN" \
  --query SecretString --output text
```

Then configure clients using files in `mcp-client-configs/`. Replace
`<ALB_DNS_NAME>` and `<TOKEN>` with the values from above.

### Step 5 — Use it

In Claude Code / Codex / Cursor:

```
> Run terraform plan for the staging profile
> Show me the plan diff
> Apply the plan
```

## Security model

| Permission | Scope |
|---|---|
| Terraform state backend | S3 + DynamoDB + KMS decrypt |
| AWS read-only | describe*/list* on EC2, ECS, ELB, RDS, DynamoDB, SQS/SNS, S3, IAM (ro), KMS, CloudWatch, ECR |
| Secrets Manager | GetSecretValue on auth token + GitHub PAT |
| Deny | IAM writes, Organizations, Billing |

The `DEPLOYMENT_PROFILE` env var is set on the ECS task (not the client). Clients authenticate via the auth token only.

## Health check note

The ALB target group health check hits `GET /` on port 8080 expecting 200. If tfmcp doesn't return 200 on `/`, the ALB shows unhealthy and traffic is not routed. Fix: check tfmcp's served paths in CloudWatch logs, then adjust `health_check.path` in `terraform/modules/tfmcp/main.tf`. Do **not** disable `wait_for_steady_state` — that only short-circuits the Terraform waiter; it does not make the target healthy.

## Profile gating

| Profile | tfmcp? |
|---|---|
| staging | No |
| production-lean | Opt-in (`enable_tfmcp_in_lean = true`) |
| production-scale | Yes (default) |
| enterprise-isolated | Yes (default) |

## Cost

One Fargate task at 512 CPU / 1024 MiB: ~$7–15/month depending on region and
Fargate pricing. No NAT Gateway (public_ip egress, same as staging/lean).

> The production-lean profile's cost model and budget ceiling are tracked in
> [`config/deployment_profiles.yaml`](../config/deployment_profiles.yaml). If
> you enable tfmcp in lean, re-run the cost model (`scripts/release/check_cost_model.py`)
> and confirm the total stays within the profile's budget before applying.

## References

- [tfmcp upstream](https://github.com/nwiizo/tfmcp) — v0.2.2
- [Aether production deployment](../../docs/PRODUCTION-DEPLOYMENT.md)
- [Aether AWS lean production](../../docs/AWS-LEAN-PRODUCTION.md)
- [MCP spec — Streamable HTTP](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)
- [Aether deployment runbook](../../docs/DEPLOYMENT-RUNBOOK.md)
- [Reviewed Terraform promotion workflow](../../.github/workflows/terraform-promote.yml)

