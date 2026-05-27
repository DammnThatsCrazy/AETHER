# ============================================================================
# AETHER — Root Module
# Orchestrates all infrastructure modules for the AETHER platform.
#
# Deployment order:
#   1. VPC (network foundation)
#   2. ECR  (container registries — needed before ECS task defs)
#   3. Secrets Manager (secret placeholders — ECS references ARNs)
#   4. Data stores: RDS, ElastiCache, MSK, Neptune
#   5. ALB (load balancer — ECS services register targets)
#   6. ECS (compute — references ALB target groups + secret ARNs)
#   7. Monitoring (references ECS cluster + ALB)
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

  environment           = var.environment
  project               = var.project
  vpc_cidr              = var.vpc_cidr
  availability_zones    = slice(data.aws_availability_zones.available.names, 0, 3)
  enable_nat_gateway_ha = var.enable_nat_gateway_ha
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
# 4a. RDS Postgres
# Kept for rollback safety. Active database is Aurora Serverless v2 (E3).
# Decommission after 72 h of clean prod metrics.
# ---------------------------------------------------------------------------

module "rds" {
  source = "./modules/rds"

  environment              = var.environment
  project                  = var.project
  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.isolated_subnet_ids
  rds_sg_id                = module.vpc.rds_sg_id
  db_instance_class        = var.db_instance_class
  db_name                  = var.db_name
  multi_az                 = var.db_multi_az
  allocated_storage        = var.db_allocated_storage
  max_allocated_storage    = var.db_max_allocated_storage
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
# 4b. ElastiCache Redis
# Kept for rollback safety. ECS uses DynamoDB cache when dynamodb_cache_table
# is wired in (E1). Decommission after 72 h of clean prod metrics.
# ---------------------------------------------------------------------------

module "elasticache" {
  source = "./modules/elasticache"

  environment      = var.environment
  project          = var.project
  vpc_id           = module.vpc.vpc_id
  subnet_ids       = module.vpc.isolated_subnet_ids
  redis_sg_id      = module.vpc.redis_sg_id
  node_type        = var.redis_node_type
  num_cache_nodes  = var.redis_num_cache_nodes
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
# 4c. MSK Kafka
# Kept for rollback safety. ECS uses SQS when sqs_queue_url is wired in (E1).
# Decommission after 72 h of clean prod metrics.
# ---------------------------------------------------------------------------

module "msk" {
  source = "./modules/msk"

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
# 4d. Neptune (Graph DB)
# ---------------------------------------------------------------------------

module "neptune" {
  source = "./modules/neptune"

  environment     = var.environment
  project         = var.project
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.isolated_subnet_ids
  neptune_sg_id   = module.vpc.neptune_sg_id
  instance_class  = var.neptune_instance_class
  cluster_size    = var.neptune_cluster_size
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
}

# ---------------------------------------------------------------------------
# 6. ECS (Fargate)
# ---------------------------------------------------------------------------

module "ecs" {
  source = "./modules/ecs"

  environment              = var.environment
  project                  = var.project
  vpc_id                   = module.vpc.vpc_id
  private_subnet_ids       = module.vpc.private_subnet_ids
  ecs_sg_id                = module.vpc.ecs_sg_id
  ecr_backend_url          = module.ecr.repository_urls["aether-backend"]
  ecr_ml_url               = module.ecr.repository_urls["aether-ml-serving"]
  alb_backend_tg_arn       = module.alb.backend_target_group_arn
  alb_ml_tg_arn            = module.alb.ml_target_group_arn
  secret_arns              = merge(module.secrets.secret_arns, {
    # E3: Aurora Serverless v2 replaces RDS as the active database.
    # entrypoint.sh reads this ARN via DATABASE_URL_SECRET and builds DATABASE_URL.
    "db-password"      = module.aurora.db_password_secret_arn
    "redis-auth-token" = module.elasticache.auth_token_secret_arn
  })
  companion_secret_arns    = module.secrets.companion_secret_arns

  # E1: SQS replaces Kafka; DynamoDB replaces Redis as the active backend.
  # Old MSK/ElastiCache vars left wired so rollback is a single variable swap.
  sqs_queue_url            = module.sqs.queue_url
  sqs_queue_arn            = module.sqs.queue_arn
  dynamodb_cache_table     = module.dynamodb_cache.table_name
  dynamodb_cache_table_arn = module.dynamodb_cache.table_arn
  # kafka/redis kept but no longer used by the task definition when sqs/dynamo are set
  kafka_bootstrap_servers  = module.msk.bootstrap_brokers_tls
  redis_host               = split(":", module.elasticache.primary_endpoint)[0]
  redis_port               = module.elasticache.port
  neptune_endpoint         = module.neptune.cluster_endpoint
  # ML_SERVING_URL: set to ALB DNS once DNS/cert is in place; empty = backend uses "not_trained" fallback
  ml_serving_url          = ""

  # E2: ML predict routes run in-process inside aether-app. The dedicated
  # aether-ml-serving ECS service is kept at desired_count=0 for rollback;
  # flip ml_serving_inline=false to restore it instantly.
  ml_serving_inline        = true

  use_fargate_spot         = true
  backend_cpu              = var.ecs_backend_cpu
  backend_memory           = var.ecs_backend_memory
  ml_cpu                   = var.ecs_ml_cpu
  ml_memory                = var.ecs_ml_memory
  backend_min_capacity     = var.ecs_backend_min_capacity
  backend_max_capacity     = var.ecs_backend_max_capacity
  ml_min_capacity          = var.ecs_ml_min_capacity
  ml_max_capacity          = var.ecs_ml_max_capacity

  log_retention_days       = var.log_retention_days
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
  aurora_cluster_id    = module.aurora.cluster_identifier
  alb_arn_suffix       = module.alb.alb_arn_suffix
  alert_email          = var.alert_email
  log_retention_days   = var.log_retention_days
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

  kyber_callback_urls  = ["${var.kyber_app_url}/callback"]
  kyber_logout_urls    = [var.kyber_app_url]
  kyber_web_origins    = [var.kyber_app_url]
}
