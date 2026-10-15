# ═══════════════════════════════════════════════════════════════════════════
# Aether Infrastructure -- Terraform Main
# Remote state in S3 + DynamoDB locking
# Per-environment state isolation via backend-config key override
# ═══════════════════════════════════════════════════════════════════════════

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }

  # State backend -- key is overridden per environment via -backend-config
  backend "s3" {
    bucket         = "aether-terraform-state"
    key            = "infrastructure/terraform.tfstate"  # overridden at init
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
      Repository  = "aether-monorepo"
    }
  }
}


# ── Variables ─────────────────────────────────────────────────────────────

variable "environment" {
  type        = string
  description = "Deployment environment: dev, staging, production"

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "Environment must be dev, staging, or production."
  }
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "image_tag" {
  type        = string
  description = "Docker image tag for ECS services"
  default     = "latest"
}

variable "ecr_registry" {
  type        = string
  description = "ECR registry URL"
}

variable "alert_email" {
  type        = string
  description = "Email for CloudWatch alarm notifications"
  default     = "ops@olympuslabsml.com"
}


# ── Modules ───────────────────────────────────────────────────────────────

module "vpc" {
  source      = "../modules/vpc"
  environment = var.environment
  aws_region  = var.aws_region
}

module "ecs" {
  source       = "../modules/ecs"
  environment  = var.environment
  vpc_id       = module.vpc.vpc_id
  subnet_ids   = module.vpc.private_subnet_ids
  image_tag    = var.image_tag
  ecr_registry = var.ecr_registry
}

module "rds" {
  source      = "../modules/rds"
  environment = var.environment
  vpc_id      = module.vpc.vpc_id
  subnet_ids  = module.vpc.private_subnet_ids
}

module "elasticache" {
  source      = "../modules/elasticache"
  environment = var.environment
  vpc_id      = module.vpc.vpc_id
  subnet_ids  = module.vpc.private_subnet_ids
}

module "neptune" {
  source      = "../modules/neptune"
  environment = var.environment
  vpc_id      = module.vpc.vpc_id
  subnet_ids  = module.vpc.private_subnet_ids
}

module "s3" {
  source      = "../modules/s3"
  environment = var.environment
}

module "cloudfront" {
  source        = "../modules/cloudfront"
  environment   = var.environment
  s3_bucket_arn = module.s3.cdn_bucket_arn
}

module "sagemaker" {
  source      = "../modules/sagemaker"
  environment = var.environment
  vpc_id      = module.vpc.vpc_id
  subnet_ids  = module.vpc.private_subnet_ids
}

module "monitoring" {
  source       = "../modules/monitoring"
  environment  = var.environment
  ecs_cluster  = module.ecs.cluster_name
  alert_email  = var.alert_email
  service_arns = module.ecs.service_arns
}

module "iam" {
  source      = "../modules/iam"
  environment = var.environment
}


# ── Outputs ───────────────────────────────────────────────────────────────

output "api_endpoint" {
  value       = module.ecs.alb_dns_name
  description = "ALB DNS name for API access"
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

output "ecs_cluster" {
  value = module.ecs.cluster_name
}

output "service_arns" {
  value = module.ecs.service_arns
}
