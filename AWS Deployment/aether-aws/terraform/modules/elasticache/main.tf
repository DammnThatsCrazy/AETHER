# ============================================================================
# AETHER — ElastiCache Redis Module
#
# Provisions a Redis 7.x cluster with:
#   - Encryption in-transit (TLS) and at-rest (KMS)
#   - Subnet group in isolated subnets
#   - Auth token stored in Secrets Manager
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
  name_prefix = "${lower(var.project)}-${var.environment}-redis7-"
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
# ElastiCache Cluster
# --------------------------------------------------------------------------

resource "aws_elasticache_cluster" "this" {
  cluster_id           = "${lower(var.project)}-${var.environment}-redis"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.node_type
  num_cache_nodes      = var.num_cache_nodes
  parameter_group_name = aws_elasticache_parameter_group.this.name
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [var.redis_sg_id]

  # Encryption — in-transit TLS and at-rest KMS
  at_rest_encryption_enabled  = true
  transit_encryption_enabled  = true
  auth_token                  = random_password.redis_auth.result

  snapshot_retention_limit = 1
  snapshot_window          = "05:00-06:00"
  maintenance_window       = "Mon:06:00-Mon:07:00"

  tags = {
    Name = "${var.project}-${var.environment}-redis"
  }
}

# --------------------------------------------------------------------------
# Redis AUTH token — stored in Secrets Manager for application retrieval
# --------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "redis_auth" {
  name                    = "aether/redis-auth-token"
  description             = "${var.project} Redis AUTH token (${var.environment})"
  kms_key_id              = aws_kms_key.redis.arn
  recovery_window_in_days = 30

  tags = {
    Name = "${var.project}-${var.environment}-redis-auth"
  }
}

resource "aws_secretsmanager_secret_version" "redis_auth" {
  secret_id     = aws_secretsmanager_secret.redis_auth.id
  secret_string = random_password.redis_auth.result
}
