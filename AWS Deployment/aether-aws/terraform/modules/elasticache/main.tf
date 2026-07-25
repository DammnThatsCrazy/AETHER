# ============================================================================
# AETHER — ElastiCache Redis Module
#
# Provisions a Redis 7.x replication group with:
#   - Encryption in-transit (TLS) and at-rest (KMS)
#   - Auth token stored in Secrets Manager
#   - Subnet group in isolated subnets
# ============================================================================

resource "random_password" "redis_auth" {
  length  = 32
  special = false
}

# --------------------------------------------------------------------------
# KMS Key
# --------------------------------------------------------------------------

resource "aws_kms_key" "redis" {
  description             = "${var.project} Redis encryption key (${var.environment})"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = {
    Name = "${var.project}-${var.environment}-redis-kms"
  }

  lifecycle {
    prevent_destroy = true

    # DECOMMISSION.md's central rule, implemented rather than only asserted:
    # "Flipping a deployment-profile toggle must never auto-destroy applied
    # stateful infrastructure." This module is instantiated with `count`, so a
    # one-word edit to var.deployment_profile takes that count to 0 and plans a
    # DESTROY of everything below. prevent_destroy turns that into a hard plan
    # error — the stop-the-line event the document calls for — instead of a diff
    # someone skims. Removing this resource for real goes through DECOMMISSION.md:
    # release it from state first (`terraform state rm`, or a `removed` block with
    # `lifecycle { destroy = false }`), then decommission it as a separate,
    # explicitly approved change.
  }
}

resource "aws_kms_alias" "redis" {
  name          = "alias/${lower(var.project)}-${var.environment}-redis"
  target_key_id = aws_kms_key.redis.key_id
}

# --------------------------------------------------------------------------
# Subnet Group
# --------------------------------------------------------------------------

resource "aws_elasticache_subnet_group" "this" {
  name       = "${lower(var.project)}-${var.environment}-redis"
  subnet_ids = var.subnet_ids

  tags = {
    Name = "${var.project}-${var.environment}-redis-subnet-group"
  }
}

# --------------------------------------------------------------------------
# Parameter Group
# --------------------------------------------------------------------------

resource "aws_elasticache_parameter_group" "this" {
  name        = "${lower(var.project)}-${var.environment}-redis7"
  family      = "redis7"
  description = "${var.project} ${var.environment} Redis 7 parameters"

  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = "${var.project}-${var.environment}-redis-pg"
  }
}

# --------------------------------------------------------------------------
# ElastiCache Replication Group (Redis)
# Using replication_group for TLS + auth_token support.
# --------------------------------------------------------------------------

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${lower(var.project)}-${var.environment}-redis"
  description          = "${var.project} Redis (${var.environment})"

  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.node_type
  num_cache_clusters   = var.num_cache_nodes
  parameter_group_name = aws_elasticache_parameter_group.this.name
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [var.redis_sg_id]

  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.redis.arn
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth.result

  snapshot_retention_limit = 1
  snapshot_window          = "05:00-06:00"
  maintenance_window       = "mon:06:00-mon:07:00"

  tags = {
    Name = "${var.project}-${var.environment}-redis"
  }

  lifecycle {
    prevent_destroy = true

    # DECOMMISSION.md's central rule, implemented rather than only asserted:
    # "Flipping a deployment-profile toggle must never auto-destroy applied
    # stateful infrastructure." This module is instantiated with `count`, so a
    # one-word edit to var.deployment_profile takes that count to 0 and plans a
    # DESTROY of everything below. prevent_destroy turns that into a hard plan
    # error — the stop-the-line event the document calls for — instead of a diff
    # someone skims. Removing this resource for real goes through DECOMMISSION.md:
    # release it from state first (`terraform state rm`, or a `removed` block with
    # `lifecycle { destroy = false }`), then decommission it as a separate,
    # explicitly approved change.
  }
}

# --------------------------------------------------------------------------
# Redis AUTH token — stored in Secrets Manager for application retrieval
# --------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "redis_auth" {
  name                    = "aether/${var.environment}/redis-auth-token"
  description             = "${var.project} Redis AUTH token (${var.environment})"
  kms_key_id              = aws_kms_key.redis.arn
  recovery_window_in_days = 30

  tags = {
    Name = "${var.project}-${var.environment}-redis-auth"
  }

  lifecycle {
    prevent_destroy = true

    # DECOMMISSION.md's central rule, implemented rather than only asserted:
    # "Flipping a deployment-profile toggle must never auto-destroy applied
    # stateful infrastructure." This module is instantiated with `count`, so a
    # one-word edit to var.deployment_profile takes that count to 0 and plans a
    # DESTROY of everything below. prevent_destroy turns that into a hard plan
    # error — the stop-the-line event the document calls for — instead of a diff
    # someone skims. Removing this resource for real goes through DECOMMISSION.md:
    # release it from state first (`terraform state rm`, or a `removed` block with
    # `lifecycle { destroy = false }`), then decommission it as a separate,
    # explicitly approved change.
  }
}

resource "aws_secretsmanager_secret_version" "redis_auth" {
  secret_id     = aws_secretsmanager_secret.redis_auth.id
  secret_string = random_password.redis_auth.result
}
