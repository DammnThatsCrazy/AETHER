# ===================================================================
# Aether Demo Environment
# Fully functional environment for sales, BD, and growth demos.
# Pre-seeded with realistic data -- hand out to prospects for testing.
# Cost-optimised: ~$2,500/month target.  Single-AZ, no HA, no DR.
# ===================================================================

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = { source = "hashicorp/aws"; version = "~> 5.40" }
  }

  backend "s3" {
    bucket         = "aether-terraform-state"
    key            = "demo/terraform.tfstate"
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
      Purpose     = "Demo"
    }
  }
}

# -- Variables --------------------------------------------------------

variable "environment"        { type = string; default = "demo" }
variable "aws_region"         { type = string; default = "us-east-1" }
variable "image_tag"          { type = string; default = "latest" }
variable "ecr_registry"       { type = string }
variable "monthly_budget_usd" { type = number; default = 2500 }
variable "acm_cert_arn"       { type = string; default = "" }
variable "hosted_zone_id"     { type = string; default = "" }

# ===================================================================
# LAYER 1: NETWORK  (VPC 10.3.0.0/16, single NAT gateway)
# ===================================================================

module "vpc" {
  source      = "../../modules/vpc"
  environment = var.environment
  aws_region  = var.aws_region
  vpc_cidr    = "10.3.0.0/16"
}

module "vpc_endpoints" {
  source              = "../../modules/vpc_endpoints"
  environment         = var.environment
  vpc_id              = module.vpc.vpc_id
  private_subnet_ids  = module.vpc.private_subnet_ids
  route_table_ids     = module.vpc.private_route_table_ids
}

# ===================================================================
# LAYER 2: SECRETS  (KMS + Secrets Manager, no rotation)
# ===================================================================

module "secrets" {
  source      = "../../modules/secrets"
  environment = var.environment
}

# ===================================================================
# LAYER 3: DATA STORES  (minimal sizing, single AZ)
# ===================================================================

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

# Demo playground static hosting bucket
resource "aws_s3_bucket" "demo_playground" {
  bucket = "aether-demo-playground"

  tags = {
    Name = "aether-demo-playground"
  }
}

resource "aws_s3_bucket_website_configuration" "demo_playground" {
  bucket = aws_s3_bucket.demo_playground.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }
}

resource "aws_s3_bucket_public_access_block" "demo_playground" {
  bucket = aws_s3_bucket.demo_playground.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "demo_playground" {
  bucket = aws_s3_bucket.demo_playground.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "PublicReadGetObject"
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.demo_playground.arn}/*"
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.demo_playground]
}

# ===================================================================
# LAYER 4: COMPUTE  (ECS Fargate -- all 9 services, minimal sizing)
# ===================================================================

module "ecs" {
  source             = "../../modules/ecs"
  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  public_subnet_ids  = module.vpc.public_subnet_ids
  private_subnet_ids = module.vpc.private_subnet_ids
  image_tag          = var.image_tag
  ecr_registry       = var.ecr_registry
}

# ===================================================================
# LAYER 5: MONITORING  (CloudWatch dashboards + budget alerts)
# ===================================================================

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

# ===================================================================
# DNS (optional -- only if hosted_zone_id is provided)
# ===================================================================

resource "aws_route53_record" "demo_api" {
  count   = var.hosted_zone_id != "" ? 1 : 0
  zone_id = var.hosted_zone_id
  name    = "demo.aether.io"
  type    = "A"

  alias {
    name                   = module.ecs.alb_dns_name
    zone_id                = module.ecs.alb_zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "demo_playground_dns" {
  count   = var.hosted_zone_id != "" ? 1 : 0
  zone_id = var.hosted_zone_id
  name    = "playground.demo.aether.io"
  type    = "A"

  alias {
    name                   = aws_s3_bucket_website_configuration.demo_playground.website_domain
    zone_id                = aws_s3_bucket.demo_playground.hosted_zone_id
    evaluate_target_health = false
  }
}

# ===================================================================
# OUTPUTS
# ===================================================================

output "ecs_cluster"       { value = module.ecs.cluster_name }
output "rds_endpoint"      { value = module.rds.cluster_endpoint }
output "vpc_id"            { value = module.vpc.vpc_id }
output "api_endpoint"      { value = "https://demo.aether.io" }
output "playground_url"    { value = "http://${aws_s3_bucket_website_configuration.demo_playground.website_endpoint}" }
output "alb_dns"           { value = module.ecs.alb_dns_name }
