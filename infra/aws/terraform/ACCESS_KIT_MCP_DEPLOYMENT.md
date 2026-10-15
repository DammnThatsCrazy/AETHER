# Access Kit MCP on AWS

This runbook describes the optional customer-facing Access Kit MCP service in
the existing AETHER AWS Terraform stack. It is a separate ECS/Fargate service and ECR
repository; it does not use `modules/tfmcp`, its shared operator token, its GitHub
credential, or its Terraform mutation role.

The service is disabled by default. It shares the existing public ALB, HTTPS
listener, API hostname, VPC and ECS cluster. The ALB terminates TLS and routes
the configured MCP path to a dedicated target group. No DNS record or ACM
certificate is created for a separate MCP hostname.

The continuation create/get tools call the existing `/v1/continuations`
authority. Its API feature gate defaults off. A reviewed Terraform plan may set
`enable_access_continuations=true` to inject `AETHER_CONTINUATION_ENABLED` into
the backend API task; the option does not enable client-sync or authorize any
caller by itself. The continuation routes still require the tenant's `read` or
`write` permission. The promotion workflow exposes this as a plan-only input,
and applying a saved plan is a separate release operation.

## Request and credential boundary

The task has no Aether API key, user session, or site key. Each protocol
request carries the caller's Aether bearer credential;
the MCP host validates it through the existing `/v1/me` authority and forwards
the same request-scoped identity to tenant APIs. Optional `observe` requests
must also carry the request-specific `X-Aether-Observe-Key` and
`X-Aether-Site-ID`; those values go only to `/v1/batch`. The service does not
select a shared tenant or site identity. The bearer authenticates the MCP
request and tenant-scoped read calls; it does not grant intake authority or
select the intake tenant. The publishable key and site ID independently pass
through the canonical site-binding check at `/v1/batch`.

Delegated MCP OAuth is separately opt-in through `enable_access_mcp_oauth`.
That flag creates a dedicated Auth0 resource server whose audience is the
exact public MCP URL, with only `access_kit:read`. The MCP task serves
`/.well-known/oauth-protected-resource` and the MCP-path-specific protected
resource metadata path, advertising the configured Auth0 issuer. Missing or
invalid credentials receive an OAuth bearer challenge. The backend validates
the JWT signature, issuer, exact MCP audience, expiry and scope, then resolves
the Auth0 subject against the current durable Aether user, membership, tenant,
plan and read permission. MCP OAuth is confined to named Access Kit GET routes;
it never creates a tenant, session or API key and grants no graph mutation or
action authority. Legacy request-scoped API keys and revocable sessions remain
available when OAuth is disabled.

When delegated OAuth is enabled, Terraform generates a 32-byte service
assertion key in the protected state and stores it in the existing KMS-backed
Secrets Manager. ECS injects it only into the API and hosted MCP tasks as
`AETHER_MCP_SERVICE_ASSERTION_KEY`; task execution roles can read the secret,
while task roles receive no AWS mutation permission. The MCP service signs
each downstream OAuth read over the method, exact path and query, token hash,
and timestamp. The API requires this short-lived assertion before accepting
the MCP-audience token, so a surface header on public REST does not bypass the
MCP boundary. Rotating the key requires coordinated API and MCP task restarts.

Auth0 Dynamic Client Registration is **not** enabled by Terraform. Auth0's
open DCR permits unauthenticated client creation, while its third-party clients
need an explicit API grant. A host can instead use a reviewed preregistered
client. Before using DCR, the identity owner must approve Auth0 tenant settings,
the exact third-party delegated read grant, application consent and connection
policy, callback URI handling, rate limits, and client revocation. The MCP
service does not proxy a registration endpoint or mint OAuth tokens. Current
MCP guidance prefers Client ID Metadata Documents; DCR is a compatibility
mechanism. This repository cannot claim host onboarding or delegated OAuth
conformance until the Auth0 configuration and a real host are exercised.

The ECS task role has no attached AWS permission policy. The separate task
execution role can pull from only `aether-access-mcp`, read the optional
service assertion secret, and write to only this service's CloudWatch log
group, in addition to ECR's required authorization token call. The task
security group accepts TCP 8080 only from the existing ALB
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
| Optional OAuth resource | Exact configured public MCP URL; no alternate audience |
| Optional OAuth issuer | Auth0 HTTPS issuer; no local token validation fallback |

`access_mcp_path` changes both the application mount and ALB path rule. The
selected path must remain distinct from the internal `tfmcp` `/mcp*` reservation.
It is limited to 91 characters including the leading slash so the
path-specific OAuth metadata pattern stays within the ALB rule limit.
Readiness confirms valid service configuration; it does not verify caller
credentials or perform a downstream API health request.

## Staged publication and enablement

Enablement uses two reviewed infrastructure plans because Terraform cannot
create the ECS task until an image already exists in ECR. Use
`.github/workflows/terraform-promote.yml` for each plan/apply pair. The apply
dispatch consumes the exact binary plan artifact by run ID and checksum; the
Access MCP inputs are plan-only and an apply dispatch cannot reshape that plan.

Use only `production-scale` and keep all steps in the same AWS account,
region, and Terraform state. The ECR repository name is global within an
account and region, so `production-scale` is its canonical persistent state
owner. `production-lean`, `enterprise-isolated`, staging, and expiring `demo`
and `preview` profiles cannot create this repository or service. The selected protected GitHub environment, OIDC roles,
Terraform backend, API domain, HTTPS listener/certificate, and required
application inputs must already be configured. The production GitHub
environments and credentials are not provisioned by this change.

1. Dispatch `terraform-promote.yml` with `action=plan`, the selected profile,
   `enable_access_mcp_repository=true`, and `enable_access_mcp=false`. Review
   the exact plan and cost report, then apply that saved plan using its run ID
   and checksum. The optional `aether-access-mcp` repository uses KMS
   encryption, immutable tags, scan-on-push, and an ECR lifecycle policy that
   retains the last ten tagged images and removes untagged images after seven
   days.
2. From a clean checkout of the reviewed commit, run
   `infra/aws/terraform/scripts/publish_access_mcp_image.sh` with Docker
   Buildx, AWS CLI credentials with push permission for the intended account,
   and `AWS_REGION` set. This step can run from a secured operator workstation
   or an AWS build environment; it does not require starting the service
   locally. The script builds `linux/amd64`, pushes
   `sha-<full-commit-sha>`, and writes only the resulting immutable
   `sha256:<digest>` to stdout. It refuses dirty worktrees and an ECR
  repository that is not immutable, KMS-encrypted, and scan-on-push. It waits
  for that exact digest's scan to complete, fails on scan errors/timeouts or
  any HIGH/CRITICAL findings, and prints no digest until it passes. Since ECR
  tags are immutable, reuse the recorded digest if that commit tag already
  exists; do not try to republish it.
3. Dispatch the reviewed workflow again with `action=plan`, the same profile,
   `enable_access_mcp_repository=true`, `enable_access_mcp=true`, and the
   published digest. Set `access_mcp_desired_count` from 1 to 4. Supply
   `access_mcp_allowed_origins` as a JSON array of exact HTTPS origins only
   when browser clients need it. Enable `enable_access_mcp_oauth` only after
   the Auth0 resource, consent and client onboarding configuration has been
   reviewed; the default remains false. Review service count, cost, IAM, listener,
   and security-group changes before applying the exact plan artifact. The
   plan job independently confirms that the supplied digest exists in ECR and
   has a completed scan with zero HIGH/CRITICAL findings. Its OIDC plan role
   therefore needs `ecr:DescribeImages` and `ecr:DescribeImageScanFindings`
   scoped to `aether-access-mcp`.
4. Apply that exact plan with its run ID and checksum. The Terraform output
   `access_mcp_endpoint` gives the customer-facing HTTPS endpoint. Check the
   ECS deployment and ALB target health with the AWS console or read-only AWS
   CLI, then configure a supported remote MCP client with the endpoint and an
   Aether API key or revocable session injected through that host's secret
   manager. The apply job rechecks the same digest and scan before any AWS
   mutation, so the apply role needs the same scoped ECR read actions. The
   target group's `/readyz` probe is internal to the ALB; it is
   not exposed as an additional public route. Verify initialization, tool
   listing, tenant-scoped reads, and denied-scope behavior with the actual
   client before customer rollout.

The script does not create AWS resources or accept an application credential.
The Publish Access Kit MCP image workflow is the repeatable production path:
it runs only from main, first verifies that the production environment has at
least one required reviewer, then waits for that environment's approval before
assuming AWS_ACCESS_MCP_PUBLISH_ROLE_ARN through GitHub OIDC. It publishes
the clean checked-out commit. Configure that role's trust for
this repository and `refs/heads/main`; scope its policy to this repository
with `ecr:GetAuthorizationToken` plus
`ecr:BatchCheckLayerAvailability`, `ecr:InitiateLayerUpload`,
`ecr:UploadLayerPart`, `ecr:CompleteLayerUpload`, `ecr:PutImage`,
`ecr:DescribeRepositories`, `ecr:DescribeImages`, and
`ecr:DescribeImageScanFindings`. The workflow uploads the verified immutable
digest as an artifact for the separately reviewed Terraform plan. Terraform
creates the repository and service roles. No live AWS apply or image
publication was performed for this PR.

`.github/workflows/access-kit-container.yml` builds the same
`linux/amd64` Dockerfile on a clean GitHub-hosted runner and smoke-checks
container health, readiness, and the headless CLI entrypoint without AWS
credentials. It does not publish to ECR. The local Docker build in this work
session succeeded for `linux/amd64`; its build context was 11.36 MB. Running
the image locally returned healthy `/healthz` and ready `/readyz` responses,
and the container CLI `--help` command succeeded. The host is Apple Silicon,
so Docker used emulation. This is local image/runtime evidence, not an AWS ECS
deployment or native x86 host result. The GitHub-hosted build workflow passed
on PR #772: [the run](https://github.com/DammnThatsCrazy/AETHER/actions/runs/38205347762)
verified npm package contents, built the `linux/amd64` image, and passed
health/readiness and headless CLI smoke checks. The job
has no AWS credentials and performs no deployment. The repository currently
has no production environment, so the publisher intentionally fails closed
until that environment and at least one required reviewer are configured.

The package Dockerfile pins its Node base image by digest and the publisher
records the exact output image digest used by Terraform. The Dockerfile-specific
ignore file limits the build context to workspace manifests and the Access Kit
package and excludes Terraform caches. The first oversized build-context
attempt was superseded by the successful bounded build. No image was pushed to
ECR.

## Deployment gate and cost profile

The promotion workflow and Terraform both allow the repository and service
only in `production-scale` with `environment=production`. The plan-policy
checker accepts only the dedicated `module.access_mcp[0]` service address
when explicitly enabled. At the default two tasks, the service compute plus
five GiB of ECR storage adds an estimated USD 18.52/month before variable ALB,
CloudWatch, traffic, and data-transfer costs; the exact profile plan and cost
report remain the deployment review evidence.

The service's fixed desired count is independent of staging's sleep multiplier
and it creates no Application Auto Scaling target. Staging, demo, and preview
are blocked until their lifecycle owners include it in wake/sleep, capacity,
TTL, and cleanup checks. This PR has not applied Terraform, created the ECR
repository, published an image, or proved service/domain readiness or customer
access.

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
