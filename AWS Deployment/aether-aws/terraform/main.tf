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

  environment = var.environment
  project     = var.project
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
# 4a. RDS Postgres — legacy, never provisioned by a fresh plan
# Aurora Serverless v2 (E3) is the active database in every profile, so
# local.enable_legacy_rds is a literal false and this count is always 0. The
# block is kept so an already-applied instance can be adopted for rollback and
# retired through DECOMMISSION.md rather than destroyed by a profile flip.
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

  backup_retention_days = var.aurora_backup_retention_days
  deletion_protection   = var.environment == "production"
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
  enable_dedicated_ml = local.enable_dedicated_ml
}

# ---------------------------------------------------------------------------
# 6. ECS (Fargate)
# ---------------------------------------------------------------------------

module "ecs" {
  source = "./modules/ecs"

  environment          = var.environment
  project              = var.project
  vpc_id               = module.vpc.vpc_id
  private_subnet_ids   = module.vpc.private_subnet_ids
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
  sqs_queue_url            = module.sqs.queue_url
  sqs_queue_arn            = module.sqs.queue_arn
  sqs_role_queue_urls      = module.sqs.role_queue_urls
  sqs_role_queue_arns      = module.sqs.role_queue_arns
  sns_topic_arn            = module.sqs.fanout_topic_arn
  runtime_roles            = local.runtime_role_settings
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

  use_fargate_spot     = true
  backend_cpu          = var.ecs_backend_cpu
  backend_memory       = var.ecs_backend_memory
  ml_cpu               = var.ecs_ml_cpu
  ml_memory            = var.ecs_ml_memory
  backend_min_capacity = var.ecs_backend_min_capacity
  backend_max_capacity = var.ecs_backend_max_capacity
  ml_min_capacity      = var.ecs_ml_min_capacity
  ml_max_capacity      = var.ecs_ml_max_capacity

  log_retention_days = var.log_retention_days
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
  aurora_cluster_id = module.aurora.cluster_identifier
  aurora_max_acu    = var.aurora_max_acu
  alb_arn_suffix    = module.alb.alb_arn_suffix

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
  dynamodb_cache_table_name = module.dynamodb_cache.table_name
  sqs_queue_name            = local.sqs_queue_name
  sqs_dlq_name              = local.sqs_dlq_name

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

module "auth0" {
  source = "./modules/auth0"

  environment                    = var.environment
  auth0_domain                   = var.auth0_domain
  auth0_management_client_id     = var.auth0_management_client_id
  auth0_management_client_secret = var.auth0_management_client_secret
  api_audience                   = var.auth0_api_audience

  aether_callback_urls = ["${var.aether_app_url}/callback"]
  aether_logout_urls   = [var.aether_app_url]
  aether_web_origins   = [var.aether_app_url]

  kyber_callback_urls = ["${var.kyber_app_url}/callback"]
  kyber_logout_urls   = [var.kyber_app_url]
  kyber_web_origins   = [var.kyber_app_url]
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
    Purpose = "Immutable static SPA origin (${each.key})"
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
