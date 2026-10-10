# ============================================================================
# AETHER — ECR (Elastic Container Registry) Module
#
# Creates private ECR repositories for all AETHER container images:
#   - aether-backend     (FastAPI backend)
#   - aether-ml-serving  (ML inference service)
#   - aether-kyber       (Kyber cryptography service)
#   - aether-aether      (Core AETHER service)
#
# Each repo has:
#   - KMS encryption
#   - Lifecycle policy (keep last 10 tagged images, purge untagged)
#   - Image scan on push
# ============================================================================

# --------------------------------------------------------------------------
# KMS Key for ECR encryption
# --------------------------------------------------------------------------

resource "aws_kms_key" "ecr" {
  description             = "${var.project} ECR encryption key (${var.environment})"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = {
    Name        = "${var.project}-${var.environment}-ecr-kms"
    Environment = var.environment
  }
}

resource "aws_kms_alias" "ecr" {
  name          = "alias/${lower(var.project)}-${var.environment}-ecr"
  target_key_id = aws_kms_key.ecr.key_id
}

# --------------------------------------------------------------------------
# ECR Repositories
# --------------------------------------------------------------------------

locals {
  repos = [
    "aether-backend",
    "aether-ml-serving",
    "aether-kyber",
    "aether-aether",
  ]

  encryption_types = {
    for repository in local.repos : repository => lookup(var.repository_encryption_types, repository, "KMS")
  }

  tag_mutabilities = {
    for repository in local.repos : repository => lookup(var.repository_tag_mutabilities, repository, "MUTABLE")
  }
}

resource "aws_ecr_repository" "this" {
  for_each = toset(local.repos)

  name                 = each.value
  image_tag_mutability = local.tag_mutabilities[each.value]

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = local.encryption_types[each.value]
    # ECR encryption is immutable. The staging backend repository predates
    # Terraform and is intentionally reconciled as AWS-managed AES256; every
    # other repository remains on the staging customer-managed KMS key.
    kms_key = local.encryption_types[each.value] == "KMS" ? aws_kms_key.ecr.arn : null
  }

  tags = {
    Name    = each.value
    Service = each.value
  }
}

# --------------------------------------------------------------------------
# Lifecycle Policies
# --------------------------------------------------------------------------

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v", "release", "sha"]
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Remove untagged images older than 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
    ]
  })
}

# --------------------------------------------------------------------------
# Repository Policy — allow ECS task execution role to pull
# --------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "aws_ecr_repository_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowECSPull"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
        Action = [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:BatchCheckLayerAvailability",
        ]
      },
    ]
  })
}
