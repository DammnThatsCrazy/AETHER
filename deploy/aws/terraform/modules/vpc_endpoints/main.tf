# ═══════════════════════════════════════════════════════════════════════════
# Aether — VPC Endpoints Module (NEW)
# PrivateLink endpoints to reduce NAT costs and improve security.
# Traffic to AWS services stays on the AWS backbone.
# ═══════════════════════════════════════════════════════════════════════════

variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "route_table_ids" { type = list(string) }

# ── Security Group for Interface Endpoints ─────────────────────────────

resource "aws_security_group" "vpce" {
  name_prefix = "aether-vpce-${var.environment}-"
  description = "Security group for VPC Interface Endpoints"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.current.cidr_block]
    description = "HTTPS from VPC"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "aether-vpce-${var.environment}" }

  lifecycle { create_before_destroy = true }
}

data "aws_vpc" "current" {
  id = var.vpc_id
}

data "aws_region" "current" {}

# ── Gateway Endpoints (free, no per-hour charge) ──────────────────────

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.route_table_ids

  tags = { Name = "aether-vpce-s3-${var.environment}" }
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.route_table_ids

  tags = { Name = "aether-vpce-dynamodb-${var.environment}" }
}

# ── Interface Endpoints ───────────────────────────────────────────────
# Each costs ~$7.20/month per AZ + data processing charges.
# Selected based on traffic volume and security requirements.

resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = { Name = "aether-vpce-ecr-api-${var.environment}" }
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = { Name = "aether-vpce-ecr-dkr-${var.environment}" }
}

resource "aws_vpc_endpoint" "logs" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = { Name = "aether-vpce-logs-${var.environment}" }
}

resource "aws_vpc_endpoint" "monitoring" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.monitoring"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = { Name = "aether-vpce-monitoring-${var.environment}" }
}

resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = { Name = "aether-vpce-secretsmanager-${var.environment}" }
}

resource "aws_vpc_endpoint" "sagemaker_runtime" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.sagemaker.runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = { Name = "aether-vpce-sagemaker-${var.environment}" }
}

resource "aws_vpc_endpoint" "sqs" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.sqs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = { Name = "aether-vpce-sqs-${var.environment}" }
}

resource "aws_vpc_endpoint" "sns" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.sns"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = { Name = "aether-vpce-sns-${var.environment}" }
}

resource "aws_vpc_endpoint" "kms" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.kms"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = { Name = "aether-vpce-kms-${var.environment}" }
}

resource "aws_vpc_endpoint" "sts" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.sts"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.vpce.id]
  private_dns_enabled = true

  tags = { Name = "aether-vpce-sts-${var.environment}" }
}

# ── Outputs ────────────────────────────────────────────────────────────

output "s3_endpoint_id" { value = aws_vpc_endpoint.s3.id }
output "dynamodb_endpoint_id" { value = aws_vpc_endpoint.dynamodb.id }
output "vpce_security_group" { value = aws_security_group.vpce.id }

output "endpoint_ids" {
  value = {
    s3                = aws_vpc_endpoint.s3.id
    dynamodb          = aws_vpc_endpoint.dynamodb.id
    ecr_api           = aws_vpc_endpoint.ecr_api.id
    ecr_dkr           = aws_vpc_endpoint.ecr_dkr.id
    logs              = aws_vpc_endpoint.logs.id
    monitoring        = aws_vpc_endpoint.monitoring.id
    secretsmanager    = aws_vpc_endpoint.secretsmanager.id
    sagemaker_runtime = aws_vpc_endpoint.sagemaker_runtime.id
    sqs               = aws_vpc_endpoint.sqs.id
    sns               = aws_vpc_endpoint.sns.id
    kms               = aws_vpc_endpoint.kms.id
    sts               = aws_vpc_endpoint.sts.id
  }
}
