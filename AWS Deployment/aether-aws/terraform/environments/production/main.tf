# ═══════════════════════════════════════════════════════════════════════════
# Aether Production Environment
# Full deployment: VPC -> ECS -> Data Stores -> CDN -> API Gateway ->
#                  ML -> WAF -> Secrets -> VPC Endpoints -> Monitoring -> IAM
# Multi-AZ, auto-scaling, full monitoring, DR-ready
# ═══════════════════════════════════════════════════════════════════════════

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = { source = "hashicorp/aws"; version = "~> 5.40" }
  }

  backend "s3" {
    bucket         = "aether-terraform-state"
    key            = "production/terraform.tfstate"
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

variable "environment"      { type = string; default = "production" }
variable "aws_region"       { type = string; default = "us-east-1" }
variable "image_tag"        { type = string; default = "latest" }
variable "ecr_registry"     { type = string }
variable "acm_cert_arn"     { type = string; default = "" }
variable "hosted_zone_id"   { type = string; default = "" }
variable "monthly_budget_usd" { type = number; default = 15000 }

# ═══════════════════════════════════════════════════════════════════════
# LAYER 1: NETWORK
# ═══════════════════════════════════════════════════════════════════════

module "vpc" {
  source      = "../../modules/vpc"
  environment = var.environment
  aws_region  = var.aws_region
  vpc_cidr    = "10.2.0.0/16"
}

module "waf" {
  source      = "../../modules/waf"
  environment = var.environment
  alb_arn     = module.ecs.alb_arn
}

module "vpc_endpoints" {
  source              = "../../modules/vpc_endpoints"
  environment         = var.environment
  vpc_id              = module.vpc.vpc_id
  private_subnet_ids  = module.vpc.private_subnet_ids
  route_table_ids     = module.vpc.private_route_table_ids
}

# ═══════════════════════════════════════════════════════════════════════
# LAYER 2: SECRETS (before data stores — they reference secret ARNs)
# ═══════════════════════════════════════════════════════════════════════

module "secrets" {
  source      = "../../modules/secrets"
  environment = var.environment
}

# ═══════════════════════════════════════════════════════════════════════
# LAYER 3: DATA STORES
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

module "msk" {
  source                  = "../../modules/msk"
  environment             = var.environment
  vpc_id                  = module.vpc.vpc_id
  subnet_ids              = module.vpc.private_subnet_ids
  allowed_security_groups = [module.ecs.ecs_security_group]
}

module "opensearch" {
  source                  = "../../modules/opensearch"
  environment             = var.environment
  vpc_id                  = module.vpc.vpc_id
  subnet_ids              = module.vpc.private_subnet_ids
  allowed_security_groups = [module.ecs.ecs_security_group]
}

module "dynamodb" {
  source               = "../../modules/dynamodb"
  environment          = var.environment
  enable_global_tables = true
  dr_region            = "us-west-2"
}

module "s3" {
  source             = "../../modules/s3"
  environment        = var.environment
  dr_region          = "us-west-2"
  enable_replication = true
}

# ═══════════════════════════════════════════════════════════════════════
# LAYER 4: COMPUTE
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

module "sagemaker" {
  source              = "../../modules/sagemaker"
  environment         = var.environment
  vpc_id              = module.vpc.vpc_id
  subnet_ids          = module.vpc.private_subnet_ids
  ml_artifacts_bucket = module.s3.ml_artifacts_bucket
}

# ═══════════════════════════════════════════════════════════════════════
# LAYER 5: EDGE / CDN
# ═══════════════════════════════════════════════════════════════════════

module "cloudfront" {
  source                  = "../../modules/cloudfront"
  environment             = var.environment
  cdn_bucket_id           = module.s3.cdn_bucket
  cdn_bucket_arn          = module.s3.cdn_bucket_arn
  cdn_bucket_domain       = "${module.s3.cdn_bucket}.s3.amazonaws.com"
  dashboard_bucket_id     = module.s3.dashboard_bucket
  dashboard_bucket_domain = "${module.s3.dashboard_bucket}.s3.amazonaws.com"
  waf_acl_arn             = module.waf.web_acl_arn
  acm_cert_arn            = var.acm_cert_arn
}

module "api_gateway" {
  source           = "../../modules/api_gateway"
  environment      = var.environment
  alb_dns_name     = module.ecs.alb_dns_name
  alb_listener_arn = module.ecs.alb_listener_arn
  acm_cert_arn     = var.acm_cert_arn
  hosted_zone_id   = var.hosted_zone_id
}

# ═══════════════════════════════════════════════════════════════════════
# LAYER 6: MONITORING / SECURITY
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

output "api_endpoint"        { value = module.api_gateway.http_api_endpoint }
output "ws_endpoint"         { value = module.api_gateway.ws_api_endpoint }
output "cdn_domain"          { value = module.cloudfront.cdn_domain }
output "dashboard_domain"    { value = module.cloudfront.dashboard_domain }
output "alb_dns"             { value = module.ecs.alb_dns_name }
output "ecs_cluster"         { value = module.ecs.cluster_name }
output "rds_endpoint"        { value = module.rds.cluster_endpoint }
output "neptune_endpoint"    { value = module.neptune.cluster_endpoint }
output "redis_endpoint"      { value = module.elasticache.configuration_endpoint }
output "kafka_brokers"       { value = module.msk.bootstrap_brokers_tls }
output "opensearch_endpoint" { value = module.opensearch.endpoint }
output "sagemaker_endpoint"  { value = module.sagemaker.endpoint_name }
output "vpc_id"              { value = module.vpc.vpc_id }
output "secrets_kms_key"     { value = module.secrets.kms_key_arn }
output "vpc_endpoints"       { value = module.vpc_endpoints.endpoint_ids }
