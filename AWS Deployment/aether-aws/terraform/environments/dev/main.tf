# ═══════════════════════════════════════════════════════════════════════════
# Aether Dev Environment (NEW)
# Minimal footprint for development — single instances, no HA, no DR.
# Cost-optimised: ~$2,000/month target.
# ═══════════════════════════════════════════════════════════════════════════

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = { source = "hashicorp/aws"; version = "~> 5.40" }
  }

  backend "s3" {
    bucket         = "aether-terraform-state"
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "aether-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "Aether"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# ── Variables ──────────────────────────────────────────────────────────

variable "environment"      { type = string; default = "dev" }
variable "aws_region"       { type = string; default = "us-east-1" }
variable "image_tag"        { type = string; default = "latest" }
variable "ecr_registry"     { type = string }
variable "monthly_budget_usd" { type = number; default = 2000 }

# ═══════════════════════════════════════════════════════════════════════
# LAYER 1: NETWORK (single NAT, minimal)
# ═══════════════════════════════════════════════════════════════════════

module "vpc" {
  source      = "../../modules/vpc"
  environment = var.environment
  aws_region  = var.aws_region
  vpc_cidr    = "10.0.0.0/16"
}

# VPC endpoints for dev — Gateway only (free) to save costs
module "vpc_endpoints" {
  source              = "../../modules/vpc_endpoints"
  environment         = var.environment
  vpc_id              = module.vpc.vpc_id
  private_subnet_ids  = module.vpc.private_subnet_ids
  route_table_ids     = module.vpc.private_route_table_ids
}

# ═══════════════════════════════════════════════════════════════════════
# LAYER 2: SECRETS
# ═══════════════════════════════════════════════════════════════════════

module "secrets" {
  source      = "../../modules/secrets"
  environment = var.environment
}

# ═══════════════════════════════════════════════════════════════════════
# LAYER 3: DATA STORES (smallest instances, single AZ)
# ═══════════════════════════════════════════════════════════════════════

module "rds" {
  source                  = "../../modules/rds"
  environment             = var.environment
  vpc_id                  = module.vpc.vpc_id
  subnet_ids              = module.vpc.private_subnet_ids
  allowed_security_groups = [module.ecs.ecs_security_group]
}

module "neptune" {
  source                  = "../../modules/neptune"
  environment             = var.environment
  vpc_id                  = module.vpc.vpc_id
  subnet_ids              = module.vpc.private_subnet_ids
  allowed_security_groups = [module.ecs.ecs_security_group]
}

module "elasticache" {
  source                  = "../../modules/elasticache"
  environment             = var.environment
  vpc_id                  = module.vpc.vpc_id
  subnet_ids              = module.vpc.private_subnet_ids
  allowed_security_groups = [module.ecs.ecs_security_group]
}

module "dynamodb" {
  source               = "../../modules/dynamodb"
  environment          = var.environment
  enable_global_tables = false
  dr_region            = ""
}

module "s3" {
  source             = "../../modules/s3"
  environment        = var.environment
  dr_region          = ""
  enable_replication = false
}

# ═══════════════════════════════════════════════════════════════════════
# LAYER 4: COMPUTE (minimal, single task per service)
# ═══════════════════════════════════════════════════════════════════════

module "ecs" {
  source             = "../../modules/ecs"
  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  public_subnet_ids  = module.vpc.public_subnet_ids
  private_subnet_ids = module.vpc.private_subnet_ids
  image_tag          = var.image_tag
  ecr_registry       = var.ecr_registry
}

# ═══════════════════════════════════════════════════════════════════════
# LAYER 5: MONITORING (basic)
# ═══════════════════════════════════════════════════════════════════════

module "monitoring" {
  source             = "../../modules/monitoring"
  environment        = var.environment
  ecs_cluster_name   = module.ecs.cluster_name
  service_names      = module.ecs.service_names
  monthly_budget_usd = var.monthly_budget_usd
}

module "iam" {
  source      = "../../modules/iam"
  environment = var.environment
}

# ═══════════════════════════════════════════════════════════════════════
# OUTPUTS
# ═══════════════════════════════════════════════════════════════════════

output "ecs_cluster"  { value = module.ecs.cluster_name }
output "rds_endpoint" { value = module.rds.cluster_endpoint }
output "vpc_id"       { value = module.vpc.vpc_id }
