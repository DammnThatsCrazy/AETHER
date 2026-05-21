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
# 4b. ElastiCache Redis
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
# 4c. MSK Kafka
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
    "db-password"      = module.rds.db_password_secret_arn
    "redis-auth-token" = module.elasticache.auth_token_secret_arn
  })

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

  environment        = var.environment
  project            = var.project
  ecs_cluster_name   = module.ecs.cluster_name
  backend_service_name = module.ecs.backend_service_name
  ml_service_name    = module.ecs.ml_service_name
  rds_identifier     = module.rds.db_instance_identifier
  alb_arn_suffix     = module.alb.alb_arn_suffix
  alert_email        = var.alert_email
  log_retention_days = var.log_retention_days
}
