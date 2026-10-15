---
title: Deployment Profiles
slug: operations/deployment-profiles
section: operations
visibility: I
audience: [ops, architect]
status: stable
since_version: 0.1.0
source_files: [config/deployment_profiles.yaml, config/runtime_deployment.yaml, config/terraform_resource_contracts.yaml, config/aws_price_book.yaml, infra/aws/terraform/profiles.tf, infra/aws/terraform/main.tf, infra/aws/terraform/modules/alb/main.tf, infra/aws/terraform/modules/aurora/main.tf, infra/aws/terraform/modules/ecr/main.tf, infra/aws/terraform/modules/secrets/main.tf, infra/aws/terraform/modules/secrets/rotation.tf, infra/aws/terraform/modules/kms_credentials/main.tf, infra/aws/terraform/variables.tf, scripts/release/check_profile_config.py, scripts/release/check_profile_parity.py, scripts/release/check_staging_lane_contract.py, scripts/release/check_cost_model.py, config/capability_overlays.yaml, scripts/validate_capability_overlays.py]
canonical_owner: platform@aether
estimated_read_minutes: 22
toc_depth: 3
reviewed_source_commits:
  - commit: "609a3ad37"
    reason: "Reviewed the Access Kit Auth0 client work. The linked root main.tf change is comment-only; the Native CLI application is an Auth0 module resource and does not alter deployment profile topology or runtime resource selection, so this profile guide needed no body change."
source_hashes:
  "config/aws_price_book.yaml": "sha256:428e6099d0a5d2d985c8675b6f382a30403ef9690464f75dff192cc60199ba19"
  "config/capability_overlays.yaml": "sha256:aab4be2180c27275e54164100963b8c3fda947fbcceecb99114bc6412f923407"
  "config/deployment_profiles.yaml": "sha256:77d37f2c71472b5d644da32636bb68948263250739b62b621502cdfb09797475"
  "config/runtime_deployment.yaml": "sha256:ba7bd71d79e605a88076b6ea745582dce9c4bff38442ebd5d327cfee9bbf7284"
  "config/terraform_resource_contracts.yaml": "sha256:1f08c04dae8931f845c7918328504f748a9f643bc806670a32b644eb8231baca"
  "infra/aws/terraform/main.tf": "sha256:abbc4c82ac24d6880bc64d75509f595ecd495cbd5c8c5dcd64173e94a8c411d0"
  "infra/aws/terraform/modules/alb/main.tf": "sha256:4ea488e53a1cdd02d47bd5d67d4d047fb43ee8eeaa04e2b419b29aab9d4a0d1a"
  "infra/aws/terraform/modules/aurora/main.tf": "sha256:afb45881042e91e038652ba1fd155d94c3213d551f9f213285552055b6415ed8"
  "infra/aws/terraform/modules/ecr/main.tf": "sha256:f880cb8a6a4dfec313b115d89e6714906dcfcf3dc1cd4496945d7e86814d6407"
  "infra/aws/terraform/modules/kms_credentials/main.tf": "sha256:c1f29a39c56575b2a62de519767aa984cb80827644c4fd6ab79d021c53172bc6"
  "infra/aws/terraform/modules/secrets/main.tf": "sha256:f872d926ac84a0bf3c473a69b9362d7bb72d3e36d0fa91ea2febc1f5b63d66e1"
  "infra/aws/terraform/modules/secrets/rotation.tf": "sha256:2e3b0bc6336ee324e3a3829f4f08c94b901501902981f87034933c875549fb00"
  "infra/aws/terraform/profiles.tf": "sha256:c197af7ebf1556be22a70dbf05c4ba85f5f93a2dd322dc39a42442f27226a89d"
  "infra/aws/terraform/variables.tf": "sha256:07d18a015db9196e8768822f33c671a0937cd96ad2c3d1ad651e24e8563f6bd9"
  "scripts/release/check_cost_model.py": "sha256:b80c15e6d0ceee9a161ad4259c82284469da10a395ac08c3b0e26f0c44e95aa7"
  "scripts/release/check_profile_config.py": "sha256:c1a16a2c7342d7be2d16306f1a15915cf4d37ffc4f1c6ea0466e3fe2df71782b"
  "scripts/release/check_profile_parity.py": "sha256:34c8ae168107d6c5e69c26dd2081c9774b42dd158b9663189ff5e70b6415adf2"
  "scripts/release/check_staging_lane_contract.py": "sha256:385a5e2316e8c38d33e10119f996854af3a7f3bc9034ca3b3545829638c8122d"
  "scripts/validate_capability_overlays.py": "sha256:adb635ee0fb3f005ea3be1f56d67d6d421e1282bbb4852986e77ad19dc381a26"
---

# Deployment Profiles

Staging uses inline ML and therefore does not require an ML image digest;
remote-ML profiles do. Its apply role is scoped to staging. The provider-
credential KMS key policy retains account-root administration by default;
profile-specific key administrators are added only through the explicit
`kms_key_admin_role_arns` input.
Aurora and the pay-per-use DynamoDB cache are present in every cloud Terraform
profile, so their alarms and dashboard widgets are selected by static root
profile flags. They never use resource-derived cluster or table IDs to decide
Terraform cardinality, which keeps state-import and plan-only runs resolvable
before those resources exist in state.
The shared Aurora module pins the standard provisioned Aurora PostgreSQL 16.8
release while retaining the `aurora-postgresql16` parameter-group family. This
is the currently available standard 16.x release in the staging account/region;
the previously pinned 16.4 release is not offered there.

Aether declares two deployment profiles: **`staging`** and **`production`**.
`config/deployment_profiles.yaml` is the canonical matrix — backend selectors,
cost policy and numeric budgets — and `scripts/release/check_profile_config.py`
validates it. There is no local profile: running Aether on a developer machine
needs no deployment profile.

Three things are deliberately kept apart:

| Concern | Where it lives | Changes by |
|---|---|---|
| **Where Aether runs** | the deployment profile (`staging` or `production`) | choosing the environment |
| **How much capacity it has** | task counts and sizes in `config/runtime_deployment.yaml`, Aurora capacity in `profiles/<profile>.tfvars` | editing a reviewed input — no profile switch |
| **What a customer can do** | tenant entitlements and feature flags | plan, contract and `config/capability_overlays.yaml` |

Production starts small and grows by raising capacity inputs. A heavier backend
(Redis, Kafka, Neptune, ClickHouse, a dedicated ML service, a NAT gateway) is
not part of either profile: it is added only when a measured bottleneck
justifies it, as a reviewed change that flips its toggle in `profiles.tf` and
updates the profile's cost policy and budget in the same change. Dedicated
customer infrastructure is a provisioning pattern, not a profile — see
[Dedicated customer deployments](#dedicated-customer-deployments).

Each Terraform environment entrypoint uses the same parse-safe provider and
variable block shape. Changes to those entrypoints are treated as deployment
profile changes: they must keep all profile plan tests and the cost/topology
contracts green before promotion.

Both profiles are **cloud profiles** and both are Terraform-selectable through
`var.deployment_profile`; each has a `profiles/*.tfvars` file, a plan test and a
policy contract (the parity checker pins the selectable set to the cloud set).

`scripts/release/check_profile_parity.py` enforces that every profile-count
statement in the docs stays in lockstep with the canonical matrix, so a third
profile added to `config/deployment_profiles.yaml` fails CI until the docs and
the Terraform layer are updated in the same change.

`deployment_profile` is not documentation. It drives module `count` and module
inputs in the Terraform root, so a `production` plan structurally cannot
contain a forbidden resource. See
[Terraform enforcement](#terraform-enforcement) for exactly how that is proven.

### Provider-credential KMS (`kms_credentials`)

Both profiles provision a dedicated customer-managed CMK — `credential_kms`
in its `cost_policy.required_resources` — for the durable, envelope-encrypted
provider credential authority (`modules/kms_credentials` in the Terraform root).
It is deliberately separate from the Secrets Manager CMK (`secrets_kms`): that
key encrypts static secret stubs, this one is the root of trust for every
per-tenant provider credential the `AwsKmsEnvelopeCredentialCipher` writes, and
the two carry different rotation, access and blast-radius profiles.

The wiring is enforced at four layers:

1. **Policy** — `credential_kms` is a required resource in both profiles'
   `cost_policy`, and `config/terraform_resource_contracts.yaml`
   contracts it as `exactly:2` resources (`aws_kms_key` + `aws_kms_alias`)
   under `module.kms_credentials`.
2. **Plan** — `profiles.tf` sets `enable_credential_kms = true`, the root
   instantiates the module behind that count, and the provider-mocked
   `profile_plan.tftest.hcl` asserts `length(module.kms_credentials) == 1` for
   both profiles.
3. **Task definition** — the key id is injected into both the api and every
   runtime-service task as `CREDENTIAL_KMS_KEY_ID`, so the backend's cipher
   resolves its key at boot (staging/production run `CREDENTIAL_CIPHER=aws_kms`).
4. **Authorization** — the module's `iam_policy_json` is attached to the ECS
   task role via `aws_iam_role_policy`, constraining the task to the four
   envelope-crypto actions under exactly the five-key
   `{tenant_id, provider, environment, slot_name, credential_version}`
   encryption context.

The `aws_iam_role_policy` attachment is the binding grant (rather than the
module's `task_role_arns` input) to avoid a module dependency cycle: the ECS
task role lives inside `module.ecs`, and `module.ecs` consumes this module's
key id for `CREDENTIAL_KMS_KEY_ID`.

## Canonical environments and capability overlays

Profiles describe environments; flags describe capabilities. There are two
environment names, one per profile (`canonical_environments` in
`config/deployment_profiles.yaml`). No Terraform state key or profile name is
renamed by the mapping.

| Environment | Profile |
|---|---|
| `staging` | `staging`, lanes `full` and `pilot`, runtime states `awake` and `asleep` |
| `production` | `production` |

The staging `pilot` lane is customer-pilot **staging** and must not be renamed
into production. `scripts/release/check_profile_config.py` checks that every
profile is mapped exactly once or unmapped (never both), that staging lanes equal
the profile's `deployment_lanes`, and that `production` maps to exactly the
`production` profile.

Capabilities are `enable-*` overlays in `config/capability_overlays.yaml`, each
realized by existing runtime flags from `services/api/config/settings.py`
(`scripts/validate_capability_overlays.py`, run by `make repo-doctor` and as a
router check in every PR plan). A bound flag must be an environment variable the
settings file actually reads, matched by whole name, and an overlay must never
equal a profile name, with or without its `enable-` prefix. A settings field that
nothing reads cannot exist (`scripts/validate_settings_flags.py`), so a bound flag
is always one the runtime consults. Four overlays are bound today (communications,
agent beta, Kyber internal, advanced value); four names are reserved and unbound
because no runtime flag exists yet (`enable-campaigns`, whose two flags were never
read and are retired, `enable-x402-experimental`, `enable-gcp-oauth`,
`enable-sovereign-controls`).

## Profile summary

| Profile | Class | Selectable in Terraform | Cost-capped | Runtime execution mode | NAT gateways |
|---|---|---|---|---|---|
| `staging` | staging | **yes** | yes (USD 25 / 50) | `consolidated` — 2 tasks | **0** |
| `production` | production | **yes** | yes (USD 150 / 200) | `consolidated` — 2 tasks | **0** |

### Immutable release digest requirements

Every selectable profile requires an immutable `backend_image_digest` from the
approved release manifest. `ml_image_digest` is not required: both profiles run
inline ML (`remote_ml` is false) and start no dedicated ML service, so it stays
empty and is validated only when provided.

The repository's live credential inventory currently arms only the staging
promotion/lifecycle path and the `staging-terraform` environment. The
production GitHub environment (`production-lean-terraform`, whose name predates
the profile consolidation) and its profile-specific OIDC role are not configured
yet. The workflow
fails closed when one of those inputs is absent; an in-repo profile definition
or an automatically created empty GitHub environment is not provisioning
evidence.

Staging is not considered runnable merely because its Terraform plan is green.
The lifecycle rehearsal also requires a verified `AetherStagingLifecycle` role,
an awake lease written before apply, and an effective apply-policy simulation
for every mutating AWS action. ECR repository ownership is classified before
planning: a canonical-but-tainted repository is repaired with the explicit
untaint path, a remote repository absent from state uses the confirmation-gated
import path, and ambiguous or cross-profile ownership stops the run. Any state
change invalidates the previous plan and requires a new reviewed plan for the
same immutable release digest.

The staging apply contract also checks the AWS account plan before mutation.
Free-plan accounts are permitted when the reviewed plan uses express mode
(AWS-managed Aurora encryption with no customer-managed KMS key); a plan
containing customer-managed Aurora KMS resources on a free account fails
closed. Free-tier accounts that cannot provision Aurora at all set
`skip_aurora = true`; Aurora is omitted from the staging `required_resources`
list for this reason, while production profiles still require it.
Paid accounts may proceed after the normal policy and cost gates. State
reconciliation can import pre-existing Secrets Manager metadata only after
verifying the exact staging CMK and `AWSCURRENT` version; values are populated
through the separate secure bootstrap and are never read by CI. For the
pilot's first-admin handoff, the AWS Secrets Manager bootstrap token and the
durable GitHub `STAGING_ADMIN_API_KEY` are separate credentials: the pilot task
arms the one-time route, and the lifecycle validates the returned `ak_...` key
against `/v1/me` with admin scope before rehearsal mutation.
The staging ECS API and consolidated worker mount the Google workforce client
ID and secret from those reviewed secret records. Workforce enforcement,
backend authorization, device trust, scope v2, and step-up are explicitly on;
the legacy operator identity and bootstrap paths are explicitly off. The
Google callback uses the staging API origin, while the Kyber application origin
is reserved for WebAuthn relying-party validation.

---

## Local development (no profile)

Running Aether on a developer machine needs no deployment profile, and none
exists. `docker-compose up` starts Postgres and one backend process with inline
ML; `docker-compose --profile full up` (or the narrower `workers`, `streaming`,
`analytics` and `integration` compose profiles) adds Redis, LocalStack,
ClickHouse, Kafka, MLflow and one container per worker role. Local development
is not a deployment target: the `all` role is a local/test convenience token and
is **never deployable** (`scripts/release/check_delivery_topology.py` enforces
that), and memory-backed cache and event bus are forbidden in anything deployed.
`scripts/validate_infra.py` carries the two local backend shapes it needs
(`local`, `local-full`) itself rather than reading them from the matrix.

Work is promoted `Development` → `staging` → `main`. A change is exercised on a
developer machine, merged to `Development` (which deploys the development web
build), promoted to `staging` (which rehearses the release), and only then to
`main` (production), when the owner decides.

Validation: `pytest`, `npm test`, `make ci-check`; `make integration-durable`
and `make integration-faults` need Docker and must not be silently skipped for a
release verdict.

## `staging`

### Apply contract

Staging applies consume the exact reviewed Terraform plan; they do not
re-plan on the apply runner. The apply job must receive the dedicated staging
AWS role and, when Auth0 resources are present, the three Auth0 provider
credentials as process environment variables. Static SPA origins use
S3-safe, lowercase hyphenated tag values, and runtime log metric filters with
dimensions omit a CloudWatch default value. These details are part of the
staging profile's apply contract and are covered by the provider-input and
Terraform profile checks before a wake is authorized.

The profile's customer-managed KMS keys are tagged with `Environment = staging`.
The Secrets Manager key policy permits only same-account Secrets Manager use and
regional CloudWatch Logs use, constrained by caller account and the AETHER
staging log namespace (Secrets Manager additionally uses `kms:ViaService`;
CloudWatch Logs omits it because the service calls KMS as its own principal
where that condition key is absent); it does not grant services unrestricted
key access. ECR and Aurora keys carry the same environment tag so the reviewed
staging apply policy can scope grants to staging resources. These tags and
service conditions are part of the Terraform profile shape and must remain
covered by the profile plan and cost/topology gates before promotion.

The public web hosts are `www`, `aether`, `docs`, `app`, and `status`: under
`staging.olympuslabsml.com` on staging and under `olympuslabsml.com` for
production. Staging serves them from two Amplify applications: the
Aether marketing app builds the unified Olympus + Aether site
(`apps/public-site`) for the `aether`, `www`, `docs` and `status` hosts, and the
end-user app serves `app`; the old Olympus, docs and status staging apps are
deleted. Production keeps five apps, one per host (Olympus marketing, Aether
marketing with the prerendered build, docs, the end-user app, and status), for
now. Kyber is not one of those public apps and
has no public DNS route. The protected tenant and Kyber release archives remain
private S3 artifacts for the staging rehearsal and internal operator path.

The release pipeline creates `aether-backend` before Terraform can adopt the
repository. It is therefore an intentional staging exception: that repository
is immutable and AES-256 encrypted, while `aether-ml-serving`, `aether-kyber`,
and `aether-aether` remain mutable and use the staging customer-managed KMS
key. ECR encryption cannot be changed after creation, so the reconciliation
workflow validates this split and imports the existing backend without a
delete/recreate plan.

| | |
|---|---|
| **Purpose** | Release rehearsal. Wakes for validation, proves a release, returns to zero. |
| **Selection** | `terraform plan -var-file=profiles/staging.tfvars`, or `.github/workflows/staging-lifecycle.yml`, which dispatches `terraform-promote.yml` for every mutation. `environment = "staging"` is set explicitly; the root default is `production`. |
| **Deployment lane** | `deployment_lane=full` preserves this existing release rehearsal. `deployment_lane=pilot` is an additive, complete lean AWS staging lane that keeps `deployment_profile=staging` and the unchanged `profiles/staging/terraform.tfstate` state key; it does not create a second Terraform profile or state namespace. |
| **Pilot contract** | Pilot retains all five public Aether/Olympus hosts (served by the unified site and the end-user app), the AWS backend, durable Aurora/persistence, networking, Secrets Manager, tenant isolation, Stripe billing/webhooks/entitlements, CloudWatch observability, lifecycle/redeploy controls, migrations and full smoke coverage. Only Kyber operator/workforce identity and GCP/Google hosting/credentials are deferred. The existing Kyber Auth0 client association is preserved by the one shared enabled-client-set resource; its duplicate Terraform state address is forgotten without destroying remote state. Pilot plans fail closed on ECS service replacement or capacity-provider strategy drift, autoscaling-target replacement or identity/role/maximum-capacity drift, Application Auto Scaling ownership-tag drift, destructive Aether Auth0 changes, or Auth0 mutations outside the Aether path. `scripts/release/check_staging_lane_contract.py` fails closed until ECS/bootstrap Stripe wiring is complete and the four real self-service Stripe test price secrets (`aether/stripe-price-{alpha,beta,gamma,delta}`) have populated current versions; Epsilon/Omicron/Omega remain optional contract-tier mappings, and the yearly Beta/Gamma/Delta prices (`aether/stripe-price-{beta,gamma,delta}-annual`) are mounted only with `stripe_annual_prices_enabled`. The staging profile turns that flag on, so the checker then also requires the three yearly secrets to have populated current versions. Bootstrap validates identifiers before write and no price IDs are invented. |
| **Resource inventory** | Aurora Serverless v2 (`aurora_min_acu = 0`, max 2), DynamoDB cache, SNS → per-role SQS queues + DLQs, S3 object lake, private S3 SPA artifacts + SSM pointers, one Amplify public web app (`AETHER-staging-web`: the unified site for `www`, `aether`, `docs`, `status` and `app`, with the end-user app under `aether.*/app`; plus one unconnected Amplify app for per-PR previews when `enable_frontend_previews` is on; see [Preview Environments](../operations/PREVIEW-ENVIRONMENTS.md)), ALB, Secrets/KMS, CloudWatch alarms, inline ML, Postgres graph. **Zero** MSK, ElastiCache, Neptune, ClickHouse, dedicated ML, frontend ECS, legacy RDS, NAT gateways, Elastic IPs and self-managed Prometheus/Grafana. The reviewed paid-account staging profile uses the customer-managed Aurora KMS key; free-tier rehearsals may set `aurora_express_mode = true` or `skip_aurora = true` according to the account-plan guard. Aurora and Postgres graph remain omitted from the staging `required_resources` list only so a free-tier rehearsal can defer them safely. |
| **Runtime topology** | `execution_mode: consolidated`. Two always-on tasks when awake: `api` (1 vCPU / 2 GiB, max 2) and `lean-worker` (1 vCPU / 4 GiB, max 2) hosting all eight worker roles. `staging_state: asleep` drives every desired count and both autoscaling bounds to zero. |
| **Data behaviour** | `database`/`graph`/`analytics: aurora_postgres`/`postgres`, `cache: dynamodb`, `event: sns_sqs`, `object: s3`, `ml: inline`. The canonical and retained legacy staging Aurora clusters use 0–2 ACU and auto-pause after 300 idle seconds; storage and other non-compute charges continue. For the imported legacy cluster, Terraform manages only this scaling configuration and preserves its existing write-forwarding and final-snapshot settings. |
| **Network behaviour** | `network_egress_mode = "public_ip"` → `nat_mode = "none"`. Tasks carry a public IP on the task ENI for egress; inbound is governed entirely by the task security group, which accepts traffic only from the ALB. |
| **Cost posture** | Target USD 25/month, hard ceiling USD 50/month, against a declared `maximum_scheduled_awake_hours_per_month: 40`. Hourly resources are prorated by awake hours; per-month charges (KMS keys, secrets, alarms) accrue regardless of sleep. **Known gap:** sleep stops ECS tasks and pauses Aurora, but the ALB and its per-AZ public IPv4 addresses keep billing while staging is asleep (about USD 27/month, observed in the live account). The budget model prorates the ALB by awake hours, so it understates the idle bill; the observed idle floor of a provisioned staging is roughly USD 45–55/month. Removing the ALB while asleep ("deep sleep") would cut that, and would need its own reviewed change to the ALB module, target groups and DNS record. See [Cost Optimization](../operations/COST-OPTIMIZATION.md). |
| **TTL / lifecycle** | An awake lease is written to SSM at wake (1–8 h, default 4). `.github/workflows/staging-ttl-guard.yml` runs hourly, treats a missing or unparseable lease as **expired**, scales services to zero and clamps each staging autoscaling target to `0..0`, then fails the run so the lapse is visible. Not armed without `AWS_STAGING_LIFECYCLE_ROLE_ARN` — it then has no credential to read the lease or enforce the TTL, reports it is a NO-OP and passes green, which is **not** a claim that staging is asleep; it re-arms fail-closed the moment the role is wired. Full procedure: [Staging Wake / Sleep](../operations/STAGING-WAKE-SLEEP.md). |
| **Security posture** | Same isolation shape as production. The rehearsal itself probes cross-tenant reads, unauthenticated access and empty-state behaviour with two distinct tenants. |
| **Validation** | `make test-staging-lifecycle`, `make test-terraform-profiles` (run blocks `staging_profile_plan` and `staging_asleep_profile_plan`), `make deployment-profile-gate`. |
| **Limitations** | No rehearsal has been executed against real AWS. Every lifecycle control is code-complete and externally unverified — see [Readiness](#readiness-and-what-is-externally-blocked). |
| **Promotion path** | Staging is not promoted. It rehearses the artifact that `production` will receive. |

## `production`

| | |
|---|---|
| **Purpose** | Founding tenant and early controlled production — the smallest footprint that runs the whole platform for a first paying customer. |
| **Selection** | `terraform plan -var-file=profiles/production.tfvars`. It is also the root default for `var.deployment_profile`. |
| **Resource inventory** | Identical runtime class list to `staging`, sized for production: Aurora Serverless v2 (`aurora_min_acu = 0.5`, max 4), DynamoDB cache, SNS/SQS + DLQs, S3 object lake, private S3 tenant/Kyber artifacts + SSM pointers, five Amplify public web apps with the production custom-domain associations, ALB, Secrets/KMS, CloudWatch alarms, inline ML, Postgres graph. **Zero** MSK, ElastiCache, Neptune, ClickHouse, dedicated ML, frontend ECS, legacy RDS, NAT gateways, Elastic IPs, Prometheus/Grafana. |
| **Runtime topology** | `execution_mode: consolidated`. Two always-on tasks: `api` (1 vCPU / 2 GiB, max 4) and `lean-worker` (2 vCPU / 8 GiB, max 4) hosting all eight worker roles. No Spot at any capacity, because the task hosts `outbox-relay`. |
| **Data behaviour** | Aurora Postgres is the database, graph and analytics of record. DynamoDB is the cache. SNS/SQS is the event substrate. ML runs in-process (`remote_ml: false`), so the semantic classifier is a resident model in the `lean-worker` task. |
| **Network behaviour** | `network_egress_mode = "public_ip"` → `nat_mode = "none"`. NAT is *forbidden unless explicit*: setting this variable to a NAT mode is the explicit opt-in and must be reviewed as a cost-policy exception. |
| **Cost posture** | Fixed baseline measures **USD 188.93/month** — USD 38.93 over the USD 150 target and USD 11.07 under the USD 200 hard ceiling. The gate warns and passes. The deviation is reviewed and **accepted**, with both closing levers examined and declined; the full analysis and approval record is in [Cost Optimization](../operations/COST-OPTIMIZATION.md). Expected usage-variable cost is a further USD 107.22/month and is not bounded by the ceiling. |
| **TTL / lifecycle** | None. This profile runs continuously; 730 h/month is the pricing basis. |
| **Security posture** | Data stores in isolated subnets with no default route. Secrets fetched at container start from Secrets Manager; no secret values in task definitions or state. ALB enforces TLS 1.3 minimum. VPC flow logs on. Tasks carry a public IP for egress; inbound is ALB-only via the security group. |
| **Validation** | `make deployment-profile-gate` runs the whole no-credentials chain. `make test-terraform-profiles` proves the planned module cardinality; `make validate-terraform-profile-policy` and `make validate-cost-model` score a plan inventory. |
| **Limitations** | Never applied, never billed, never load-tested. First application of the consolidated shape **destroys seven ECS services** on any workspace that already applied the per-role shape — see [Migration hazards](#migration-hazards). Uses `environment = "production"`, so it belongs in its own AWS account, separate from staging. |
| **Promotion path** | Receives the artifact that `staging` rehearsed. Grows by capacity inputs, not by changing profile — see [How production grows](#how-production-grows). |


**tfmcp (opt-in).** `production` supports an optional Terraform MCP server
via `enable_tfmcp_in_lean = true` in the profile tfvars. When enabled, one
Fargate task (512 CPU / 1024 MiB, `public_ip` egress) serves the MCP protocol
over Streamable HTTP on port 8080 behind the shared ALB at `/mcp*`. The task
role grants scoped Terraform state access, an apply policy covering the resource
classes this root manages, and Secrets Manager reads for the auth token and
GitHub PAT. The endpoint uses the configured `domain_name` (cert-backed HTTPS)
when set. Enabling tfmcp raises the lean fixed baseline by roughly USD 18/month;
the USD 200 hard ceiling is exceeded and must be reviewed as a cost-policy
exception. See [AWS Deployment](../operations/AWS-DEPLOYMENT.md#tfmcp--terraform-mcp-server)
and `infra/aws/terraform/modules/tfmcp`.

**Customer Access Kit MCP (opt-in).** This is a separate, non-privileged
customer endpoint from `tfmcp`. `enable_access_mcp_repository` provisions the
immutable `aether-access-mcp` ECR repository; after a reviewed image publish,
`enable_access_mcp` adds a digest-pinned Fargate service and HTTPS ALB route at
`/v1/access/mcp`. It accepts caller Aether credentials per request and has no
shared tenant secret or workload AWS permissions. The service is allowed only
on `production`, the single persistent state that owns the globally
named ECR repository; staging is rejected. The service is disabled by default. A separate
`enable_access_mcp_oauth` opt-in adds the Auth0 MCP audience and a KMS-backed
service assertion secret shared only by the MCP and API tasks; MCP-audience
tokens cannot be replayed directly to the public REST API.
`enable_access_continuations` independently enables the existing continuation
API on the backend task for named Access Kit create/readback, with caller
`write`/`read` permissions still enforced. Both options default off and
require a reviewed plan. For cost comparison only, the modeled two-task service
plus ECR adds about USD 18.52/month to a USD 188.93 fixed baseline, or USD
207.45/month before variable charges; this exceeds the USD 200 hard ceiling.
See the
[Access Kit MCP AWS deployment runbook](../../infra/aws/terraform/ACCESS_KIT_MCP_DEPLOYMENT.md).
## How production grows

`production` is one profile. Moving from a first design partner to many customers
changes **capacity inputs**, each a reviewed edit with a Terraform plan, and
leaves the architecture alone. Scale the bottleneck, not the platform.

| Symptom | Input to change | Where |
|---|---|---|
| API latency or saturation | `api` `desired_count`, `autoscaling.max_capacity`, `cpu`, `memory` | `config/runtime_deployment.yaml` → `profiles.production.services.api` |
| Ingestion or queue age rising | `lean-worker` `desired_count`, `autoscaling.max_capacity`, `cpu`, `memory` | `config/runtime_deployment.yaml` → `profiles.production.services.lean-worker` |
| Database CPU or connection pressure | `aurora_min_acu`, `aurora_max_acu` | `infra/aws/terraform/profiles/production.tfvars` |
| Log cost | `log_retention_days` | `infra/aws/terraform/profiles/production.tfvars` |

Anything beyond that is a design decision, not a size change, and is made only
on measured evidence:

- **One worker role needs its own scaling or blast radius.** Give it its own
  service entry in `config/runtime_deployment.yaml` and remove it from
  `lean-worker`'s roles. The one-owner invariant in `check_delivery_topology.py`
  keeps the split safe. The validator supports the `dedicated` shape (one task per
  role); a mixed shape would need a small validator extension.
- **Graph queries are slow.** Optimise queries, indexes and Aurora capacity
  first. Neptune is a last resort and needs a cost-policy and budget change.
- **ML inference slows the API or costs too much.** Move the relevant inference
  out to its own service (`remote_ml`).
- **SQS cannot meet a streaming requirement.** Evaluate Kafka against measured
  throughput, ordering, retention and replay needs.

Each of those flips a toggle in `profiles.tf` that is a literal `false` today.
`check_cost_policy_terraform.py` requires every forbidden toggle to be false for
`production`, so enabling one means editing `config/deployment_profiles.yaml`'s
`production.cost_policy` and `budget` in the same change — the cost gate is the
review, not an afterthought. The modules under `infra/aws/terraform/modules/`
(`elasticache`, `msk`, `neptune`, `rds`) stay in the repository for that day.

## Dedicated customer deployments

A customer who needs isolation by contract or regulation does not need a
different profile. The pattern is the same `production` profile applied in a
**separate AWS account**, with its own state key and its own tfvars file.
Because the two share `environment = "production"`, resource names would collide
within one account; separate state keys do not prevent that, so a separate
account is required.

What is technically available: a dedicated VPC with three-tier subnets, data
stores in isolated subnets with no default route, a dedicated Aurora, queues,
S3 and customer-managed KMS keys, VPC flow logs, TLS 1.3 minimum at the ALB, and
least-privilege task IAM. A customer who also needs private egress opts in
explicitly through `network_egress_mode`, reviewed as a cost-policy exception.

What is **not** claimed: no FedRAMP authorization, no government accreditation,
no contractual isolation guarantee, no regional data-sovereignty claim, and no
dedicated account has been provisioned — every control that depends on one is
externally unverified. Data-rights and training permissions are separate from
deployment isolation and are enforced independently.

---

## Runtime topology — schema v2

`config/runtime_deployment.yaml` is the canonical deployable topology, and its
unit is the **ECS service, not the logical role**. Schema v1's flat `roles:` map
was replaced because the deployable unit changed.

A `services:` entry is one ECS service and one task definition. Its `roles:`
list names the logical roles that one process hosts. `execution_mode` names the
packing strategy:

- **`consolidated`** — one task hosts several logical roles through an execution
  group token (`services/api/workers/runtime/roles.py::EXECUTION_GROUPS`).
  `production` and `staging` run **2 always-on tasks, not 10**: `api`, plus
  one `lean-worker` whose task hosts all eight worker roles —
  `outbox-relay`, `stream-worker`, `identity-worker`, `graph-writer`,
  `measurement-worker`, `semantic-worker`, `materializer`, `maintenance`.
- **`dedicated`** — one task per logical role, where per-role scaling and
  per-role blast radius are worth eight extra task definitions. No committed
  profile uses it today; the validator keeps it supported for the day a role is
  split out (see [How production grows](#how-production-grows)).

**Consolidation moves the process boundary and nothing else.** Inside a
consolidated task every member role keeps its own queue, consumer group, DLQ,
retry policy, backpressure budget, metrics label and restart behaviour, resolved
in-process by `services/api/workers/runtime/roles.py::roles_in` and
`services/api/workers/runtime/consumer_specs.py`. Terraform carries the role list for one
reason only: a consolidated task must bind one SQS queue per hosted role, which
a single `SQS_QUEUE_URL` cannot express.

Two invariants are enforced by `scripts/release/check_delivery_topology.py`:

- Every role in `roles.py::WORKER_ROLES` is hosted by **exactly one** service in
  **every** profile — never orphaned, never claimed twice. `api` never hosts a
  worker role or a consumer, and the local/test role `all` is never deployable.
- Spot is forbidden outright on `api` and on any service hosting
  `outbox-relay`, so a Spot reclaim can never interrupt public traffic or the
  at-least-once delivery path.

The service key **is** the `AETHER_ROLE` token the container boots with, which
is why the consolidated service is keyed `lean-worker` and not `workers`. A
service key maps 1:1 to `"<project>-<env>-<key>"` with one load-bearing
exception: `api` is served by the Terraform-provisioned
`"<project>-<env>-backend"` service. `deploy.yml` special-cases that mapping and
`check_delivery_topology.py` pins it in both places.

### `staging_state`

`staging` declares a `staging_state` block with `awake` (multiplier 1) and
`asleep` (multiplier 0). Both lanes scale `desired_count` and both autoscaling
bounds; full also scales capacity-provider `base_count`, while pilot pins that
field to zero in both states to keep the ECS service strategy invariant:

| Scaled | Why |
|---|---|
| `desired_count` | The obvious one, and on its own not enough. |
| autoscaling `min_capacity` | Application Auto Scaling clamps a service back up to its floor. A floor of 1 against a desired count of 0 revives the task within a cooldown, so staging never sleeps while appearing to. |
| autoscaling `max_capacity` | A non-zero ceiling lets target-tracking policies scale a service out on queue or request metrics. The asleep plan pins both bounds to zero until a reviewed wake restores the declared envelope. |
| capacity provider `base_count` | Full lane scales the guaranteed floor and rejects `base_count > desired_count`; pilot holds the FARGATE strategy at base 0 because strategy changes force service replacement. |

The declared `max_capacity` is the awake surge envelope. Asleep plans set it to
zero along with the floor, preventing attached target-tracking policies from
reviving staging. The reviewed wake plan restores the declared minimum and
maximum. Pilot asleep/awake plans retain the same services and
capacity-provider strategy; `check_terraform_plan_policy.py` blocks apply if a
pilot plan includes service replacement or managed scaling-tag removal.

`staging_state` is a **plan-time input** to `terraform-promote.yml`. An apply
consumes the stored plan and cannot reshape it. A profile with no `staging_state`
block (production) is always at full capacity and ignores the input.

Validate with `make test-runtime-topology` and `make validate-delivery-topology`.

---

## Terraform enforcement

The Terraform root at `infra/aws/terraform/` selects a profile
through `var.deployment_profile`, validated to one of `staging` and
`production` (default `production`). `profiles.tf` derives `enable_*` locals from it, and
`main.tf` wires those into module `count` and module inputs.

Enforcement is proven at three distinct layers. They check different things and
none of them substitutes for another.

### 1. Static tripwire — locals resolve to false

`make validate-cost-policy-terraform`
(`scripts/release/check_cost_policy_terraform.py`) reads `profiles.tf` as text
and statically evaluates each toggle. Every forbidden toggle is the literal
`false` (or a closed boolean expression over the profile locals that evaluates
false for `production`):

| Forbidden resource | Terraform local | Derivation |
|---|---|---|
| `msk` | `enable_msk` | literal `false` |
| `elasticache` | `enable_elasticache` | literal `false` |
| `neptune` | `enable_neptune` | literal `false` |
| `clickhouse` | `enable_clickhouse` | literal `false` (selector only) |
| `dedicated_ml_service` | `enable_dedicated_ml` | literal `false` |
| `nat_gateway_unless_explicit` | `enable_nat_gateway` | literal `false` (opt in with `network_egress_mode`) |
| `frontend_ecs_services` | `enable_frontend_ecs` | literal `false` |
| `legacy_rds` | `enable_legacy_rds` | literal `false` |
| `prometheus_grafana_servers` | `enable_prometheus_grafana` | literal `false` |

The validator also asserts that the `deployment_profile` variable and its
validation exist, and that each `profiles/*.tfvars` sets a profile matching its
filename. It needs no plan and no credentials, so it catches a regression the
moment it is written. It runs in `release-gate` and
`founding-tenant-release-gate`, not in `ci-check`.

### 2. Config-plan tests — planned module cardinality

`make test-terraform-profiles` runs `terraform validate` and then
`terraform test -filter=tests/profile_plan.tftest.hcl`. The provider-mocked run
blocks — `staging_profile_plan`, `staging_asleep_profile_plan`,
`production_profile_plan`, plus the pilot-lane, applied-state, Access Kit MCP and
egress-rejection blocks — assert against the **planned module graph**, not
against the locals that produced it:

```hcl
length(module.msk)              == 0    # production
length(module.vpc.nat_gateway_ids) == 0
module.vpc.nat_mode             == "none"
```

Reading the graph rather than the locals is the point: a local that stops being
wired into a `count` is caught rather than passed over. The assertions are
**mutation-proven** — forcing `count = 1` on MSK fails the production run block with
`module.msk is tuple with 1 element`. No AWS credentials are required.

### 3. Plan policy — a real plan JSON, scored against contracts

`scripts/release/check_terraform_plan_policy.py` reads an actual
`terraform show -json` plan, derives a canonical resource inventory
(`.artifacts/profile-resource-inventory.json`) and scores it against
`config/terraform_resource_contracts.yaml`, which maps every policy key to the
module address and cardinality a conforming plan must show. This is the layer
that catches a resource the locals never modelled.

```bash
make validate-terraform-profile-policy   # defaults to the committed production fixture
make validate-cost-model                 # prices that inventory against the budget
make test-plan-policy                    # validator against pass/fail fixtures
```

`PLAN_JSON` defaults to `tests/fixtures/terraform_plans/production-valid.json`
so the gate is runnable without credentials. CI overrides it with a real plan.
Both `infrastructure.yml` and `terraform-promote.yml` run the validator against
plan JSON they produced, and the cost model against the inventory it emitted.

### What the enforcement does *not* prove

A configuration plan is not an applied environment. Neither the mocked run
blocks nor the fixture-scored policy result demonstrates that a plan was
produced with credentials against the real remote state, and none of them
demonstrates that anything was applied. Reviewers must distinguish
configuration-plan evidence from environment-authoritative remote-plan
evidence, and must read the latter before promotion. `always_on_staging_compute`
in particular has nothing to count in a production plan — it is a lifecycle
property enforced by the staging automation, not a plan assertion.

---

## Promotion and the apply path

`.github/workflows/infrastructure.yml` is **plan-and-validate only and never
applies Terraform.** The job that auto-applied the production profile on every
push to `main` has been **deleted**. What remains there:

- a provider-mocked configuration plan for each of the two profiles
  on each finalized infrastructure-impact PR, publishing an immutable `terraform-configuration-plan-*` artifact;
- an OIDC remote plan per cloud profile when the complete credential set is
  present, publishing `terraform-remote-plan-*` plus the policy and cost reports;
- `require-production-credentials`, which on a push to `main` gates
  **promotability**, not an apply: a commit is only dispatchable for promotion
  if its main-branch run proved the credential set exists and all four profiles
  produced a credentialed, policy- and cost-validated remote plan. When the
  credentialed remote-plan lane is held. An explicit remote-plan dispatch must
  provide the exact immutable backend digest and commit SHA plus the complete
  credential set; missing or malformed inputs fail closed before AWS or
  Terraform work. Provider-mocked configuration plans remain available for
  repository evidence.

`.github/workflows/terraform-promote.yml` is the **sole apply path**. It is
`workflow_dispatch`-only — no push, tag, schedule or path trigger can reach an
apply — and the apply job consumes the exact binary plan the plan job produced.
**Apply never re-plans.** Before it runs it verifies:

| Bound | Check |
|---|---|
| Plan identity | `reviewed.tfplan` digest equals the dispatched `plan_checksum`, and `sha256sum --check` passes on the recorded manifest |
| Profile | `reviewed.profile` equals the dispatched profile |
| State key | `reviewed.state-key` equals `profiles/<profile>/terraform.tfstate` |
| State backend | `reviewed.state-bucket` and `reviewed.state-lock-table` equal the backend secrets used by the apply |
| Commit | apply checks out the plan's **own recorded commit**, not the dispatch ref, and verifies `HEAD` matches |
| Terraform version | the installed version equals `reviewed.terraform-version` |
| Lockfile | `sha256(.terraform.lock.hcl)` equals `reviewed.lock.sha256`, captured before `init` |
| Expiry | the plan is **valid for 24 hours**; a longer claimed window, an inverted window or an expired plan all fail |
| Policy and cost | `check_terraform_plan_policy.py` and `check_cost_model.py` are re-run at the reviewed commit — the artifact reports are evidence, not proof |

Approval is per profile. The apply job binds to a distinct GitHub environment —
`staging-terraform` and `production-lean-terraform` (production's name predates
the profile consolidation; GitHub environments cannot be renamed) — so staging
cannot borrow production's reviewers and production cannot be applied behind
staging's.

`staging_state` (`awake` | `asleep`) is a plan-time input recorded alongside the
plan as `reviewed.staging-state`, so a reviewer can see which shape was
approved. Production ignores it.

`.github/workflows/staging-lifecycle.yml` never runs `terraform apply` itself;
every mutation is a dispatch of `terraform-promote.yml`, and it independently
re-verifies the reviewed plan (including asserting the planned ECS desired
counts and autoscaling bounds match the pinned `awake`/`asleep` shape) before
dispatching. `.github/workflows/staging-ttl-guard.yml` deliberately runs no
Terraform at all: its only enforcement action is ECS scale-to-zero plus
clamping staging autoscaling bounds to `0..0`, which can only reduce running
compute.

---

## Migration hazards

Three hazards apply to the first application of the current profile shape. All
three are correct and intended; each needs planning.

- **Seven ECS services are destroyed.** Collapsing eight dedicated worker
  services into one `lean-worker` is a genuine **destroy of seven ECS
  services** on any workspace that already applied the per-role shape. This is
  not hidden behind `moved` blocks and must not be: it is a change of
  deployment unit, not a rename. Queues, DLQs, consumer groups and retry
  policies all survive; the roles are re-hosted, not removed. Plan for a gap
  between the old services draining and the new task becoming healthy.
- **The private default route is a maintenance window.** The NAT default route
  moved from an inline `route` attribute inside `aws_route_table.private` to a
  standalone `aws_route.private_nat`. `moved` **cannot** express this — an
  inline route block is an attribute, not an addressable resource, so there is
  nothing to move from. On the first apply against a NAT-carrying workspace
  (a workspace that opted into `single_nat` or `ha_nat`) Terraform performs two unordered
  operations on the live egress path. Apply it alone, expect a brief egress
  outage, and afterwards verify each private route table has exactly one
  `0.0.0.0/0` route to the intended gateway — in `ha` mode, the NAT in the same
  AZ. `nat_mode = "none"` workspaces, which is what both profiles use by
  default, are unaffected.
- **Staging and production collide on resource names if they share an account.**
  Both are cost-capped profiles with `environment` defaulting to `production`;
  only `staging.tfvars` overrides it, and resource names are
  `${var.project}-${var.environment}`. Separate state keys keep the *state* apart
  and do nothing about the *names*. **Production belongs in its own AWS
  account** — and so does any dedicated customer deployment.

The mirror-image hazard — adding `count` to a module renaming its state address
from `module.x` to `module.x[0]`, which would otherwise plan a
destroy-and-recreate of a live cluster — is covered by 14 `moved` blocks in
`moved.tf`. Do not delete them until every pre-existing workspace has applied at
least once. Intentional removal of any data store goes through
`infra/aws/terraform/DECOMMISSION.md`, never through a profile
toggle.

### Dead second Terraform tree

`infra/aws/terraform/environments/{dev,staging,production,demo}/`
and `docs/archive/legacy-architecture/aws-deployment/main.tf` are a second, **dead** Terraform tree. Between them
they reference seven modules that do not exist in this repository —
`cloudfront`, `opensearch`, `dynamodb`, `sagemaker`, `api_gateway`, `iam`,
`waf` — so `terraform init` fails there, and `environments/demo/main.tf` is not
valid HCL. It is not the deployment path and nothing applies it. Do not modify,
extend, "fix" or copy patterns out of it.

---

## Readiness, and what is externally blocked

Readiness is reported as three numbers by
`make deployment-readiness-score` (`scripts/release/check_deployment_readiness.py`)
against `config/deployment_readiness.yaml`. **They are never merged into one
number**, and the code-complete column must never be quoted as "the score".

| Scorecard | Code-complete | Externally verified | Gate (on externally verified) |
|---|---|---|---|
| overall | 100 / 100 | **20 / 100** | 90 |
| `production` | 100 / 100 † | **20 / 100** | 92 |
| `staging` | 75 / 100 | **0 / 100** | 95 |

† 80 / 100 in a clean checkout. `LEAN-COST-CEILING` requires
`docs/reference/reports/cost/cost-report.json`, which is generated and gitignored; it reaches
100 only after `make validate-cost-model` has written it, as
`make deployment-profile-gate` does before scoring.

**1 of 17 hard gate conditions is met** (`COND-NO-EXPIRED-EXCEPTIONS`), and
`deployment_ready` is `false`.

Externally blocked — recorded as blocked, never counted as done:

- credentialed `terraform plan` and `terraform apply` against the real backend
  and state key;
- a real staging wake → validate → sleep rehearsal, and the **two consecutive**
  complete rehearsals the 100% gate requires;
- Infracost's credentialed second opinion on the cost model;
- seven days of observed AWS billing plus projected-vs-actual reconciliation;
- sustained load observation against a deployed environment;
- DNS and TLS certificate confirmation against real hostnames;
- enterprise dedicated-account provisioning.

## Validation commands

```bash
make deployment-profile-gate          # every profile gate that runs without AWS credentials
make resolved-feature-flags            # explicit staging and production flag manifests
make validate-profile-config          # profile matrix + posture schema
make validate-cost-policy             # forbidden/required resource declarations
make validate-cost-policy-terraform   # Terraform locals statically encode the policy
make validate-profile-parity          # cross-source profile-set agreement
make validate-delivery-topology       # every worker role owned by exactly one service
make validate-terraform-profile-policy # score a real plan JSON against the contracts
make validate-cost-model              # price the inventory against the numeric budget
make validate-staging-budget          # staging awake/asleep budget (plan-policy + cost model)
make test-terraform-profiles          # provider-mocked per-profile plan tests
make test-runtime-topology            # execution-group topology
make test-plan-policy                 # plan-policy validator against fixtures
make test-workflow-controls           # no automatic apply, reviewed-plan integrity
make test-cost-model                  # ceilings, fail-closed pricing, exception expiry
make test-staging-lifecycle           # wake/sleep + TTL guard structural controls
make test-ttl-guard                   # TTL lease guard used by staging wake/sleep
make deployment-readiness-score       # the three-column scorecard
make collect-deployment-evidence      # materialise release-evidence/ with its checksum
```

## See also

### Staging state reconciliation

If a staging resource exists in AWS but is absent from the reviewed Terraform
state, reconcile state before generating a replacement plan. The guarded
`Reconcile staging Terraform state` workflow accepts only the exact
`aether-staging-backend` target-group ARN, imports only
`module.alb.aws_lb_target_group.backend[0]`, and refuses deletes or replacements.
After an import, discard the old binary plan and produce a fresh staging plan
and checksum before any apply.

If state still contains the pre-split, unindexed address
`module.alb.aws_lb_target_group.backend`, do not use the reconciliation workflow
first. Dispatch the confirmation-gated
`.github/workflows/terraform-state-migrate.yml` workflow with the affected
profile and `MIGRATE-TARGET-GROUP`. That workflow performs only the reviewed
state-address move (staging to `backend[0]`, production to
`backend_replacement[0]`) and shares the promotion concurrency group so it
cannot race a plan or apply. Once it succeeds, discard any prior plan and run a
new plan-only promotion to regenerate the reviewed plan, inventory, checksum,
and expiry before applying.

- [AWS Lean Production](../operations/AWS-LEAN-PRODUCTION.md) — the `production` profile in depth
- [Staging Wake / Sleep](../operations/STAGING-WAKE-SLEEP.md) — the staging lifecycle procedure
- [Cost Optimization](../operations/COST-OPTIMIZATION.md) — cost model, budgets and the accepted deviation
- [AWS Deployment — Infrastructure Reference](../operations/AWS-DEPLOYMENT.md) — what the Terraform root actually provisions
- [Deployment Runbook](../operations/DEPLOYMENT-RUNBOOK.md) — operator procedure
- [Release Evidence](../operations/RELEASE-EVIDENCE.md) — the evidence bundle
