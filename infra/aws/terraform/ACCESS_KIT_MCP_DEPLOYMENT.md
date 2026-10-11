# Access Kit MCP on AWS

This runbook describes the optional customer-facing Access Kit MCP service in
the existing AETHER AWS Terraform stack. It is a separate ECS/Fargate service and ECR
repository; it does not use `modules/tfmcp`, its shared operator token, its GitHub
credential, or its Terraform mutation role.

The service is disabled by default. It shares the existing public ALB, HTTPS
listener, API hostname, VPC and ECS cluster. The ALB terminates TLS and routes
the configured MCP path to a dedicated target group. No DNS record or ACM
certificate is created for a separate MCP hostname.

## Request and credential boundary

The task has no Aether API key, user session, site key, or other application
secret. Each protocol request carries the caller's Aether bearer credential;
the MCP host validates it through the existing `/v1/me` authority and forwards
the same request-scoped identity to tenant APIs. Optional `observe` requests
must also carry the request-specific `X-Aether-Observe-Key` and
`X-Aether-Site-ID`; those values go only to `/v1/batch`. The service does not
select a shared tenant or site identity.

The ECS task role has no attached AWS permission policy. The separate task
execution role can pull from only `aether-access-mcp` and write to only this
service's CloudWatch log group, in addition to ECR's required authorization
token call. The task security group accepts TCP 8080 only from the existing ALB
security group. It allows outbound TCP 443 for the Aether API and AWS runtime
endpoints; this is destination-wide egress because the current public-IP/NAT
profile does not provide stable endpoint IP ranges. The service has no public
task ingress, ECS Exec, autoscaling, or AWS mutation permission.

## Runtime contract

| Setting | Value |
| --- | --- |
| Build context | Repository root |
| Dockerfile | `packages/access-kit/Dockerfile` |
| Runtime command | `node ./bin/aether-mcp-http.js` |
| Container port | 8080 |
| Default route | `/v1/access/mcp` |
| Exact allowed Host | Existing `var.domain_name` API hostname |
| Configured endpoint | `https://<var.domain_name><access_mcp_path>` |
| API destination | `https://<var.domain_name>` |
| ALB readiness check | `GET /readyz`, expects 200 |
| Liveness endpoint | `GET /healthz` |
| TLS | Existing ALB HTTPS listener / ACM certificate |
| Browser Origins | Optional exact HTTPS origin list; no wildcard |

`access_mcp_path` changes both the application mount and ALB path rule. The
selected path must remain distinct from the internal `tfmcp` `/mcp*` reservation.
Readiness confirms valid service configuration; it does not verify caller
credentials or perform a downstream API health request. The service has no
OAuth dynamic-client-registration flow.

## Staged publication and enablement

Enablement has two infrastructure stages because Terraform cannot create the
ECS task until an image already exists in ECR:

1. Provision only `enable_access_mcp_repository=true`; keep
   `enable_access_mcp=false`. The optional `aether-access-mcp` repository uses
   KMS encryption, immutable tags, scan-on-push, and the ECR lifecycle policy
   that retains the last ten tagged images and removes untagged images after
   seven days.
2. From a clean checkout of the reviewed commit, run
   `infra/aws/terraform/scripts/publish_access_mcp_image.sh` with Docker
   Buildx, AWS CLI credentials for the intended account, and `AWS_REGION` set.
   The script builds `linux/amd64`, pushes `sha-<full-commit-sha>`, and writes
   only the resulting immutable `sha256:<digest>` to stdout. It refuses dirty
   worktrees and an ECR repository that is not immutable, KMS-encrypted, and
   scan-on-push. Since ECR tags are immutable, use the previously recorded
   digest if that commit tag already exists; do not try to republish it.
3. Record that digest in the reviewed Terraform plan as
   `access_mcp_image_digest`, retain `enable_access_mcp_repository=true`, and
   explicitly set `enable_access_mcp=true`. Optionally configure
   `access_mcp_allowed_origins` and `access_mcp_desired_count` (1–4 tasks). The
   ECS task image is referenced by repository digest, not by tag.

The script does not create AWS resources or accept an application credential.
The caller performing publication needs ECR authentication and push permission
for this repository. Terraform creates the repository and roles. No live AWS
apply or publication is part of this change.

The package Dockerfile currently names `node:22-bookworm-slim` by version tag,
not image digest. The publisher records the exact output image digest used by
Terraform, but rebuilding the same commit later may use a different upstream
base image. Pinning the base image digest is a package-owner prerequisite for
bit-for-bit reproducible rebuilds.

## Deployment gate and current workflow gap

The Terraform defaults keep the repository and service disabled, and service
validation requires both the repository opt-in and an immutable image digest.
The existing infrastructure/staging workflows do not currently accept or pass
these three new inputs. `scripts/release/check_terraform_plan_policy.py` counts
exactly the services declared by `config/runtime_deployment.yaml`, while the
staging lifecycle plan and sleep checks also require exact service and scaling
target sets. Those owners need an explicit optional-service policy and staging
lifecycle treatment before the normal workflows can enable it.

`config/aws_price_book.yaml` already prices ECS services generically from their
task size and desired count, and ECR repositories as an approximate storage
line. The profile budget and plan inventory still need review for this
additional fixed service and image repository; no separate MCP-specific price
formula is present. Until the service-count, budget, workflow-input, and
staging-lifecycle gates are updated, this wiring is statically reviewable, but
the ordinary staging/production promotion path cannot enable it.

The service's fixed desired count is independent of staging's sleep multiplier
and it creates no Application Auto Scaling target. Do not opt it into a staging
environment until the staging lifecycle owner includes it in wake/sleep,
capacity, and cleanup checks. Terraform has not been applied to an AWS account,
the ECR repository has not been created, and no service/domain readiness or
customer access is claimed.

## Cost envelope

At two continuously running Linux/x86 Fargate tasks, each allocated 0.25 vCPU
and 0.5 GiB, compute is approximately **$18.02 per 730-hour month** in
US East (N. Virginia), using the current listed per-second rates. Five GiB of
retained ECR image layers adds about **$0.50/month** at $0.10/GB-month. This
excludes variable ALB LCU/request charges, CloudWatch ingestion/storage, API
traffic, data transfer, image scan charges if applicable, tax, and any price or
region difference. The task count is bounded at four, with no autoscaling; a
deployment can temporarily run up to twice the configured desired count during
replacement.

AWS pricing references: [Fargate](https://aws.amazon.com/fargate/pricing/)
and [private ECR](https://aws.amazon.com/ecr/pricing/). The estimate is a
planning calculation, not an account quote.
