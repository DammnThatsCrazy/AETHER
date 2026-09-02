# ============================================================================
# AETHER — Root Module
# Orchestrates all infrastructure modules for the AETHER platform.
#
# Deployment order:
#   1. VPC (network foundation)
#   2. ECR  (container registries — needed before ECS task defs)
#   3. Secrets Manager (secret placeholders — ECS references ARNs)
#   4. Data stores: Aurora, DynamoDB, SQS/SNS always; ElastiCache, MSK,
#      Neptune and legacy RDS only when the deployment profile enables them
#   5. ALB (load balancer — ECS services register targets)
#   6. ECS (compute — references ALB target groups + secret ARNs)
#   7. Monitoring (references ECS cluster + ALB)
#
# Profile gating: the enable_* locals in profiles.tf drive `count` on the
# optional data stores. Because a counted module's outputs become a list, no
# consumer below reads those module outputs directly — everything goes through
# the normalized connection locals in section 4z, which collapse an absent
# backend to "" rather than to null or to an index error.
# ============================================================================

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# ---------------------------------------------------------------------------
# AZ Discovery
# ---------------------------------------------------------------------------

data "aws_availability_zones" "available" {
  state = "available"
}

# ---------------------------------------------------------------------------
# 1. VPC
# ---------------------------------------------------------------------------

module "vpc" {
  source = "./modules/vpc"

  environment        = var.environment
  project            = var.project
  vpc_cidr           = var.vpc_cidr
  availability_zones = slice(data.aws_availability_zones.available.names, 0, 3)

  # "none" for staging/production-lean: tasks egress via a public IP on the
  # task ENI, so the profile pays for no NAT Gateway or EIP at all.
  nat_mode = local.nat_mode

  # Data-store security groups follow the data stores. A lean VPC carries no
  # security group for a backend it does not run.
  enable_redis_sg   = local.enable_elasticache
  enable_msk_sg     = local.enable_msk
  enable_neptune_sg = local.enable_neptune
}

# ---------------------------------------------------------------------------
# 2. ECR Repositories
# ---------------------------------------------------------------------------

module "ecr" {
  source = "./modules/ecr"

  environment                 = var.environment
  project                     = var.project
  repository_encryption_types = var.ecr_repository_encryption_types
  repository_tag_mutabilities = var.ecr_repository_tag_mutabilities
}

# ---------------------------------------------------------------------------
# 3. Secrets Manager
# ---------------------------------------------------------------------------

module "secrets" {
  source = "./modules/secrets"

  environment = var.environment
  project     = var.project
}

# ---------------------------------------------------------------------------
# 3a. Provider-credential envelope-encryption CMK (modules/kms_credentials)
#
# A dedicated customer-managed CMK for the durable, envelope-encrypted provider
# credential authority. Deliberately separate from the Secrets Manager CMK
# above: that key encrypts static secret stubs, this one is the root of trust
# for every per-tenant provider credential the AwsKmsEnvelopeCredentialCipher
# writes, and the two carry different rotation, access and blast-radius
# profiles. The key id is handed to module.ecs, which surfaces it to every task
# as CREDENTIAL_KMS_KEY_ID; the task role's least-privilege crypto grant is
# attached at the end of section 6.
#
# task_role_arns is deliberately NOT passed here. The ECS task role lives inside
# module.ecs, and module.ecs consumes this module's key_id for
# CREDENTIAL_KMS_KEY_ID — passing the task role ARN in would close a module
# cycle (kms needs ecs's role arn; ecs needs kms's key id). The binding grant
# is therefore the iam_policy_json output attached via aws_iam_role_policy
# below; its kms:EncryptionContextKeys condition constrains calls to exactly
# the five-key {tenant_id, provider, environment, slot_name, credential_version}
# context, and the key policy's EnableIAMRootPermissions statement keeps that
# IAM identity policy authoritative for this key.
# ---------------------------------------------------------------------------

module "kms_credentials" {
  source = "./modules/kms_credentials"
  count  = var.enable_credential_kms ? 1 : 0

  environment         = var.environment
  project             = var.project
  key_admin_role_arns = var.kms_key_admin_role_arns
}

# ---------------------------------------------------------------------------
# 4a. RDS Postgres — legacy, never provisioned by a fresh plan
#
# Aurora Serverless v2 (E3) is the active database in every profile, so
# local.enable_legacy_rds is a literal false — a shape
# scripts/release/check_cost_policy_terraform.py requires — and this count is
# therefore always 0.
#
# WHAT THAT MEANS FOR A WORKSPACE THAT ALREADY APPLIED AN RDS INSTANCE, stated
# exactly, because the previous comment here claimed the opposite: this count
# does NOT keep an applied instance managed. moved.tf only relocates the state
# address to module.rds[0]; a count of 0 then plans a destroy of it. What stops
# that destroy is `lifecycle { prevent_destroy = true }` on
# aws_db_instance.this and aws_kms_key.rds inside modules/rds — the KMS key
# encrypts both the storage and the final snapshot, so losing it loses the
# snapshot too. Terraform therefore FAILS THE PLAN rather than destroying
# either, and the workspace stays blocked until an operator follows
# DECOMMISSION.md: release the instance from state (`terraform state rm
# 'module.rds[0]'`, or a `removed` block with `lifecycle { destroy = false }`)
# and retire it as a separate, explicitly approved change.
#
# Re-adopting a legacy instance as MANAGED infrastructure is deliberately not
# possible from a variable: legacy_rds is a forbidden resource in all four
# profiles' cost policy, so a plan containing one is a policy violation by
# construction, not an operational mode.
# ---------------------------------------------------------------------------

module "rds" {
  source = "./modules/rds"
  count  = local.enable_legacy_rds ? 1 : 0

  environment           = var.environment
  project               = var.project
  vpc_id                = module.vpc.vpc_id
  subnet_ids            = module.vpc.isolated_subnet_ids
  rds_sg_id             = module.vpc.rds_sg_id
  db_instance_class     = var.db_instance_class
  db_name               = var.db_name
  multi_az              = var.db_multi_az
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
}

# ---------------------------------------------------------------------------
# 4a-E3. Aurora Serverless v2 (replaces RDS as the active database)
# Reuses the rds_sg_id (same port 5432, same network rules).
# ---------------------------------------------------------------------------

module "aurora" {
  source = "./modules/aurora"

  environment  = var.environment
  project      = var.project
  vpc_id       = module.vpc.vpc_id
  subnet_ids   = module.vpc.isolated_subnet_ids
  aurora_sg_id = module.vpc.rds_sg_id
  db_name      = var.db_name
  min_acu      = var.aurora_min_acu
  max_acu      = var.aurora_max_acu
  # Staging uses the provider-supported Serverless v2 auto-pause field. Warm
  # production profiles leave this null and keep their configured floor.
  auto_pause_seconds = var.environment == "staging" ? 300 : null

  backup_retention_days = var.aurora_backup_retention_days
  deletion_protection   = var.environment == "production"
  express_mode          = var.aurora_express_mode
}

# ---------------------------------------------------------------------------
# 4b. ElastiCache Redis — production-scale / enterprise-isolated only.
# The cost-capped profiles cache in DynamoDB (4b-E1) and provision nothing
# here; local.cache_backend tells the running task which one is authoritative.
# ---------------------------------------------------------------------------

module "elasticache" {
  source = "./modules/elasticache"
  count  = local.enable_elasticache ? 1 : 0

  environment     = var.environment
  project         = var.project
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.isolated_subnet_ids
  redis_sg_id     = module.vpc.redis_sg_id
  node_type       = var.redis_node_type
  num_cache_nodes = var.redis_num_cache_nodes
}

# ---------------------------------------------------------------------------
# 4b-E1. DynamoDB cache table (replaces ElastiCache as active backend)
# ---------------------------------------------------------------------------

module "dynamodb_cache" {
  source = "./modules/dynamodb_cache"

  environment = var.environment
  project     = var.project
}

# ---------------------------------------------------------------------------
# 4c. MSK Kafka — production-scale / enterprise-isolated only.
# The cost-capped profiles publish through SNS→SQS (4c-E1); local.event_broker
# tells the running task which broker is authoritative.
# ---------------------------------------------------------------------------

module "msk" {
  source = "./modules/msk"
  count  = local.enable_msk ? 1 : 0

  environment          = var.environment
  project              = var.project
  vpc_id               = module.vpc.vpc_id
  subnet_ids           = module.vpc.isolated_subnet_ids
  msk_sg_id            = module.vpc.msk_sg_id
  broker_instance_type = var.msk_broker_instance_type
  kafka_version        = var.msk_kafka_version
  broker_count         = var.msk_broker_count
  broker_volume_size   = var.msk_broker_volume_size
}

# ---------------------------------------------------------------------------
# 4c-E1. SQS + SNS fanout (replaces MSK as active event broker)
# ---------------------------------------------------------------------------

module "sqs" {
  source = "./modules/sqs"

  environment = var.environment
  project     = var.project
}

# ---------------------------------------------------------------------------
# 4d. Neptune (Graph DB) — production-scale / enterprise-isolated only.
# The cost-capped profiles keep the graph in Aurora Postgres; see
# local.graph_backend.
# ---------------------------------------------------------------------------

module "neptune" {
  source = "./modules/neptune"
  count  = local.enable_neptune ? 1 : 0

  environment    = var.environment
  project        = var.project
  vpc_id         = module.vpc.vpc_id
  subnet_ids     = module.vpc.isolated_subnet_ids
  neptune_sg_id  = module.vpc.neptune_sg_id
  instance_class = var.neptune_instance_class
  cluster_size   = var.neptune_cluster_size
}

# ---------------------------------------------------------------------------
# 4z. Normalized data-store connection surface
#
# Every consumer of a profile-gated data store reads these locals, never the
# module output, because a counted module's outputs are a list and indexing an
# absent one is an error.
#
# The idiom is deliberate: `try(module.x[0].out, "")`, not
# `try(one(module.x[*].out), "")`. `one([])` returns null and `try` only traps
# errors, so the one()-form yields null and silently feeds a null into a
# string input. Indexing the empty list raises, so `try` actually fires and the
# fallback is the empty string the ECS/monitoring modules expect. Unknown
# values still propagate normally because the counts are known at plan time.
# ---------------------------------------------------------------------------

locals {
  # ElastiCache Redis (absent unless local.cache_backend == "redis").
  redis_host            = try(split(":", module.elasticache[0].primary_endpoint)[0], "")
  redis_port            = try(module.elasticache[0].port, 6379)
  redis_auth_secret_arn = try(module.elasticache[0].auth_token_secret_arn, "")

  # MSK Kafka (absent unless local.event_broker == "kafka").
  kafka_bootstrap_servers = try(module.msk[0].bootstrap_brokers_tls, "")

  # Neptune (absent unless local.graph_backend == "neptune").
  neptune_endpoint = try(module.neptune[0].cluster_endpoint, "")

  # Legacy RDS. Always absent on a fresh plan; kept so the root outputs stay
  # index-safe for a state that still carries an adopted instance.
  legacy_rds_endpoint = try(module.rds[0].endpoint, "")
  legacy_rds_port     = try(module.rds[0].port, 0)
  legacy_rds_db_name  = try(module.rds[0].db_name, "")

  # CloudWatch alarm dimensions for the gated stores.
  #
  # These MUST be configuration-derived, not read back from the module output.
  # modules/monitoring gates each alarm with
  # `count = var.enable_x && var.x_id != "" ? 1 : 0`, and a resource attribute
  # is unknown until apply — feeding one in makes the count unplannable and
  # `terraform plan` fails outright on the first apply of a scale/enterprise
  # workspace. Each string below reproduces the identifier its module
  # configures, so the value is known at plan and equal to the real one.
  # Keep in sync with modules/{elasticache,msk,neptune}/main.tf.
  elasticache_replication_group_id = local.enable_elasticache ? "${lower(var.project)}-${var.environment}-redis" : ""
  msk_cluster_name                 = local.enable_msk ? "${lower(var.project)}-${var.environment}-kafka" : ""
  neptune_cluster_id               = local.enable_neptune ? "${lower(var.project)}-${var.environment}-neptune" : ""

  # Same reasoning, plus: CloudWatch's QueueName dimension needs the queue NAME
  # and modules/sqs exposes only URLs and ARNs. Keep in sync with
  # modules/sqs/main.tf.
  sqs_queue_name = "${var.project}-${var.environment}-events"
  sqs_dlq_name   = "${var.project}-${var.environment}-events-dlq"
}

# ---------------------------------------------------------------------------
# 5. ALB (Application Load Balancer)
# ---------------------------------------------------------------------------

module "alb" {
  source = "./modules/alb"

  environment         = var.environment
  project             = var.project
  vpc_id              = module.vpc.vpc_id
  public_subnet_ids   = module.vpc.public_subnet_ids
  alb_sg_id           = module.vpc.alb_sg_id
  acm_certificate_arn = var.acm_certificate_arn

  # The ML target group and the /v1/ml/* listener rule live here, not in
  # modules/ecs, so they need the same gate as the service that registers with
  # them. Without it a lean plan still creates a forbidden, permanently empty
  # dedicated-ML target group.
  enable_dedicated_ml               = local.enable_dedicated_ml
  staging_listener_target_group_arn = var.staging_listener_target_group_arn
}

# ---------------------------------------------------------------------------
# 6. ECS (Fargate)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ECS task network placement
#
# This is an EGRESS decision, not a security one, and getting it wrong makes
# the very first apply of a cost-capped profile fail outright:
#
#   network_egress_mode = "public_ip"  ->  nat_mode = "none"
#     -> modules/vpc creates no NAT Gateway, so aws_route.private_nat has
#        count 0 and the private route tables carry NO 0.0.0.0/0 route at all.
#     -> a task ENI in a private subnet has no path to ECR, Secrets Manager or
#        CloudWatch. assign_public_ip is inert there: the public IP is on the
#        ENI, but egress still follows the SUBNET's route table, which has no
#        default route. The task cannot pull its image
#        (CannotPullContainerError), the deployment circuit breaker rolls back,
#        and the service never reaches steady state.
#     -> tasks therefore run in the PUBLIC subnets, whose route table has the
#        IGW default route (modules/vpc: aws_route_table.public), which is what
#        makes assign_public_ip actually work.
#
#   single_nat / ha_nat  ->  the private route tables do carry a NAT default
#        route, so tasks stay private and take no public IP.
#
# var.network_egress_mode also accepts "none" and "vpc_endpoints". Both leave
# assign_public_ip false, so tasks are placed private — correct for the posture
# each one names, but neither is usable today: "none" is by definition no
# egress, and this root instantiates no vpc_endpoints module (modules/
# vpc_endpoints exists but nothing calls it), so "vpc_endpoints" provisions no
# endpoints and behaves exactly like "none". Neither value is set by any
# profile or workflow. Wiring the endpoints module is tracked separately.
#
# This does NOT make a task port publicly reachable. The ECS security group
# (modules/vpc: aws_security_group.ecs, built from local.ecs_ingress_rules)
# admits 8000/8080 from the ALB security group only and has no CIDR ingress of
# any kind, so a public IP buys egress and nothing else. That invariant is
# asserted per profile in tests/profile_plan.tftest.hcl; do not weaken it while
# any profile places tasks in the public tier.
#
# Databases are unaffected — every data store stays in the isolated subnets.
# ---------------------------------------------------------------------------

locals {
  ecs_task_subnet_tier = local.assign_public_ip ? "public" : "private"
  ecs_task_subnets     = module.vpc.workload_subnets_by_tier[local.ecs_task_subnet_tier]
}

module "ecs" {
  source = "./modules/ecs"

  environment          = var.environment
  project              = var.project
  vpc_id               = module.vpc.vpc_id
  task_subnets         = local.ecs_task_subnets
  ecs_sg_id            = module.vpc.ecs_sg_id
  ecr_backend_url      = module.ecr.repository_urls["aether-backend"]
  backend_image_digest = var.backend_image_digest
  ecr_ml_url           = module.ecr.repository_urls["aether-ml-serving"]
  ml_image_digest      = var.ml_image_digest
  alb_backend_tg_arn   = module.alb.backend_target_group_arn
  alb_ml_tg_arn        = module.alb.ml_target_group_arn

  # E3: Aurora Serverless v2 replaces RDS as the active database.
  # entrypoint.sh reads this ARN via DATABASE_URL_SECRET and builds DATABASE_URL.
  # The redis-auth-token key is omitted entirely when Redis is not provisioned —
  # an empty ARN would be handed to the execution role as a valueFrom.
  secret_arns = merge(
    module.secrets.secret_arns,
    { "db-password" = module.aurora.db_password_secret_arn },
    local.redis_auth_secret_arn == "" ? {} : { "redis-auth-token" = local.redis_auth_secret_arn },
  )
  companion_secret_arns = module.secrets.companion_secret_arns

  # Which backend the task actually uses is stated explicitly rather than
  # inferred from whether a host string happens to be empty.
  event_broker      = local.event_broker
  cache_backend     = local.cache_backend
  graph_backend     = local.graph_backend
  analytics_backend = local.analytics_backend

  # Resource gating, so IAM policies and alarms only cover what exists.
  enable_elasticache  = local.enable_elasticache
  enable_msk          = local.enable_msk
  enable_neptune      = local.enable_neptune
  enable_dedicated_ml = local.enable_dedicated_ml

  # No NAT on the cost-capped profiles: tasks take a public IP on the ENI.
  assign_public_ip = local.assign_public_ip

  # SNS→SQS fanout and the DynamoDB cache table are provisioned in every
  # profile; they are the lean backends and the scale rollback target.
  sqs_queue_url       = module.sqs.queue_url
  sqs_queue_arn       = module.sqs.queue_arn
  sqs_role_queue_urls = module.sqs.role_queue_urls
  sqs_role_queue_arns = module.sqs.role_queue_arns
  sns_topic_arn       = module.sqs.fanout_topic_arn

  # Dead-letter destinations. modules/sqs has always created these queues (they
  # are the redrive target of each role queue) but never published them, so no
  # task was ever told where to dead-letter. The runtime's old fallback was to
  # re-publish the poison message onto the queue it came from, where it was
  # re-received, matched no handler and was deleted — silent loss. That
  # fallback is gone and the runtime now raises, so these four inputs are what
  # keep dead-lettering working at all.
  sqs_dlq_url             = module.sqs.dlq_url
  sqs_dlq_arn             = module.sqs.dlq_arn
  sqs_role_dlq_queue_urls = module.sqs.role_dlq_queue_urls
  sqs_role_dlq_queue_arns = module.sqs.role_dlq_queue_arns

  # The non-api half of the schema-v2 runtime matrix: one entry per deployable
  # ECS SERVICE, keyed by the AETHER_ROLE token its task boots with. A
  # consolidated profile passes one `lean-worker` entry hosting eight roles; a
  # dedicated profile passes eight single-role entries.
  runtime_services = local.runtime_service_settings

  dynamodb_cache_table     = module.dynamodb_cache.table_name
  dynamodb_cache_table_arn = module.dynamodb_cache.table_arn

  # Normalized (section 4z) — "" whenever the profile omits the backend.
  kafka_bootstrap_servers = local.kafka_bootstrap_servers
  redis_host              = local.redis_host
  redis_port              = local.redis_port
  neptune_endpoint        = local.neptune_endpoint

  # ML_SERVING_URL: set to ALB DNS once DNS/cert is in place; empty = backend uses "not_trained" fallback
  ml_serving_url = ""

  # E2: ML predict routes run in-process inside aether-app on any profile that
  # does not provision the dedicated service. Advisory only — resource creation
  # is driven by enable_dedicated_ml above.
  ml_serving_inline = !local.enable_dedicated_ml

  # Provider-credential envelope-encryption CMK id → CREDENTIAL_KMS_KEY_ID.
  # Empty when the CMK is disabled (tftest apply run passes enable_credential_kms
  # = false); module/ecs already skips injecting the env var for an empty id.
  credential_kms_key_id = try(module.kms_credentials[0].key_id, "")

  # The api service, straight from the runtime matrix (profiles.tf). There is
  # no ecs_backend_* variable to disagree with it any more, and no
  # use_fargate_spot flag: the matrix pins api to on-demand at every capacity,
  # which is what the previous `use_fargate_spot = true` was quietly violating.
  backend_cpu               = local.api_cpu
  backend_memory            = local.api_memory
  backend_desired_count     = local.api_desired_count
  backend_min_capacity      = local.api_min_capacity
  backend_max_capacity      = local.api_max_capacity
  backend_capacity_provider = local.api_capacity_provider

  # ML serving is not described by the runtime matrix (it is a service, not a
  # runtime role), so it keeps its own variables.
  ml_cpu          = var.ecs_ml_cpu
  ml_memory       = var.ecs_ml_memory
  ml_min_capacity = var.ecs_ml_min_capacity
  ml_max_capacity = var.ecs_ml_max_capacity

  log_retention_days = var.log_retention_days
}

# ---------------------------------------------------------------------------
# 6a. Provider-credential CMK — task-role crypto grant
#
# The task role may only call the four envelope-crypto actions
# (Encrypt/Decrypt/GenerateDataKey/DescribeKey) on the credential CMK, under
# exactly the five-key {tenant_id, provider, environment, slot_name,
# credential_version} encryption context — the condition lives in the attached
# policy JSON itself via kms:EncryptionContextKeys. aws_iam_role_policy.role
# takes the role NAME, hence module.ecs.task_role_name. The resource is
# count-gated on var.enable_credential_kms (default true) so a deployment that
# disables the CMK — today only the tftest apply run, whose throwaway apply
# cannot tear down a prevent_destroy resource — creates no dangling grant.
# ---------------------------------------------------------------------------

resource "aws_iam_role_policy" "credential_kms" {
  count  = var.enable_credential_kms ? 1 : 0
  name   = "${var.project}-${var.environment}-credential-kms"
  role   = module.ecs.task_role_name
  policy = module.kms_credentials[0].iam_policy_json
}

# ---------------------------------------------------------------------------
# 7. Monitoring
# ---------------------------------------------------------------------------

module "monitoring" {
  source = "./modules/monitoring"

  environment          = var.environment
  project              = var.project
  ecs_cluster_name     = module.ecs.cluster_name
  backend_service_name = module.ecs.backend_service_name
  ml_service_name      = module.ecs.ml_service_name
  # E3: Aurora is now the active database — pass cluster_identifier so
  # the monitoring module enables the Aurora ACU alarm and dashboard widget.
  # aurora_max_acu follows the profile so the max-ACU alarm threshold tracks
  # the capacity the cluster was actually given.
  aurora_cluster_id           = module.aurora.cluster_identifier
  aurora_max_acu              = var.aurora_max_acu
  enable_aurora_observability = true
  alb_arn_suffix              = module.alb.alb_arn_suffix

  # Alarm gating: a profile that provisions no Redis/Kafka/Neptune/dedicated ML
  # must not create alarms whose dimensions point at nothing — they would sit
  # permanently in INSUFFICIENT_DATA and mask real alerts.
  enable_elasticache  = local.enable_elasticache
  enable_msk          = local.enable_msk
  enable_neptune      = local.enable_neptune
  enable_dedicated_ml = local.enable_dedicated_ml

  # Dimensions for the gated stores' alarms — "" whenever the store is absent.
  elasticache_replication_group_id = local.elasticache_replication_group_id
  msk_cluster_name                 = local.msk_cluster_name
  neptune_cluster_id               = local.neptune_cluster_id

  # Alarms for the LEAN REPLACEMENT services. These are required, not optional:
  # a profile that swaps Redis for DynamoDB and Kafka for SQS and then ships no
  # alarms for DynamoDB or SQS has removed its own observability, which is the
  # failure mode the cost policy is most likely to cause.
  dynamodb_cache_table_name           = module.dynamodb_cache.table_name
  enable_dynamodb_cache_observability = local.enable_dynamodb_cache
  sqs_queue_name                      = local.sqs_queue_name
  sqs_dlq_name                        = local.sqs_dlq_name

  # A permanently-failed role inside a still-running consolidated task keeps
  # the ECS service at steady state, so the orchestrator never replaces it.
  # modules/monitoring turns the supervisor's log line into a metric and an
  # alarm; without these group names there is no alarm to raise.
  runtime_service_log_groups = module.ecs.runtime_service_log_groups

  alert_email        = var.alert_email
  log_retention_days = var.log_retention_days
}

# ---------------------------------------------------------------------------
# 8. ML Drift Lambda (nightly PSI check → Aether/MLDrift CloudWatch namespace)
# Depends on monitoring so the log_archive_bucket name is available.
# ---------------------------------------------------------------------------

module "ml_drift_lambda" {
  source = "./modules/ml_drift_lambda"

  environment = var.environment
  project     = var.project
  log_bucket  = module.monitoring.log_archive_bucket
}

# ---------------------------------------------------------------------------
# 9. Auth0 (SPA clients + API resource server)
# ---------------------------------------------------------------------------

# The Auth0 MANAGEMENT credentials are deliberately absent from this call, and
# from variables.tf. `terraform show -json` emits every root variable verbatim
# — `sensitive = true` does not redact the plan JSON's top-level `variables`
# object — so a credential held as a Terraform variable is a credential in
# every plan artifact. The provider reads AUTH0_DOMAIN, AUTH0_CLIENT_ID and
# AUTH0_CLIENT_SECRET from the runner's environment instead; see
# modules/auth0/main.tf. Nothing here needs them, so nothing here holds them.
module "auth0" {
  source = "./modules/auth0"

  environment  = var.environment
  api_audience = var.auth0_api_audience

  aether_callback_urls = ["${var.aether_app_url}/callback"]
  aether_logout_urls   = [var.aether_app_url]
  aether_web_origins   = [var.aether_app_url]

  kyber_callback_urls       = ["${var.kyber_app_url}/callback"]
  kyber_logout_urls         = [var.kyber_app_url]
  kyber_web_origins         = [var.kyber_app_url]
  enable_social_connections = var.enable_social_connections
}

# ---------------------------------------------------------------------------
# 10. Static SPA origins + SSM parameters
# Private S3 origins for the immutable SPA bundles. The deploy workflow
# resolves the bucket names from /aether/<env>/AETHER_STATIC_BUCKET and
# /aether/<env>/KYBER_STATIC_BUCKET before publishing.
# ---------------------------------------------------------------------------

locals {
  # Required in every deployable profile (config/runtime_deployment.yaml sets
  # static_frontends: true for all four). Gated anyway so the required-resource
  # side of the cost policy is enforced by the same mechanism as the forbidden
  # side, and an empty map is a visible, testable failure.
  static_frontends = local.enable_static_frontends ? {
    aether = "AETHER_STATIC_BUCKET"
    kyber  = "KYBER_STATIC_BUCKET"
  } : {}
}

resource "aws_s3_bucket" "static_frontend" {
  for_each = local.static_frontends
  bucket   = lower("${var.project}-${var.environment}-${each.key}-static")

  tags = {
    Name    = lower("${var.project}-${var.environment}-${each.key}-static")
    Purpose = "immutable-static-spa-origin-${each.key}"
  }
}

resource "aws_s3_bucket_public_access_block" "static_frontend" {
  for_each                = local.static_frontends
  bucket                  = aws_s3_bucket.static_frontend[each.key].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "static_frontend" {
  for_each = local.static_frontends
  bucket   = aws_s3_bucket.static_frontend[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_ssm_parameter" "static_frontend_bucket" {
  for_each = local.static_frontends
  name     = "/aether/${var.environment}/${each.value}"
  type     = "String"
  value    = aws_s3_bucket.static_frontend[each.key].bucket

  tags = {
    Purpose = "Static SPA origin bucket name consumed by the deploy workflow"
  }
}
