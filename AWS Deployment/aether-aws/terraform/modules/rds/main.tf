# ============================================================================
# AETHER — RDS Postgres Module
#
# Provisions a single-instance RDS Postgres 16 database with:
#   - KMS encryption at rest
#   - Automated backups (7-day retention)
#   - Multi-AZ standby (configurable)
#   - Custom parameter group (max_connections, log_connections)
#   - Password stored in Secrets Manager (secret ARN passed in)
#   - Storage autoscaling
# ============================================================================

data "aws_region" "current" {}

# --------------------------------------------------------------------------
# KMS Key for RDS encryption
# --------------------------------------------------------------------------

resource "aws_kms_key" "rds" {
  description             = "${var.project} RDS encryption key (${var.environment})"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = {
    Name = "${var.project}-${var.environment}-rds-kms"
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

resource "aws_kms_alias" "rds" {
  name          = "alias/${lower(var.project)}-${var.environment}-rds"
  target_key_id = aws_kms_key.rds.key_id
}

# --------------------------------------------------------------------------
# DB Subnet Group (uses isolated subnets)
# --------------------------------------------------------------------------

resource "aws_db_subnet_group" "this" {
  name       = "${lower(var.project)}-${var.environment}-rds"
  subnet_ids = var.subnet_ids

  tags = {
    Name = "${var.project}-${var.environment}-rds-subnet-group"
  }
}

# --------------------------------------------------------------------------
# DB Parameter Group
# --------------------------------------------------------------------------

resource "aws_db_parameter_group" "this" {
  name_prefix = "${lower(var.project)}-${var.environment}-pg16-"
  family      = "postgres16"
  description = "${var.project} ${var.environment} Postgres 16 parameters"

  parameter {
    name  = "max_connections"
    value = "200"
  }

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_disconnections"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
  }

  tags = {
    Name = "${var.project}-${var.environment}-rds-pg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# --------------------------------------------------------------------------
# RDS Instance
# --------------------------------------------------------------------------

resource "aws_db_instance" "this" {
  identifier = "${lower(var.project)}-${var.environment}-postgres"

  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class
  db_name        = var.db_name
  username       = "aether_admin"
  port           = 5432

  # AWS manages the master password — it is never stored in Terraform state.
  # The credential JSON is placed in Secrets Manager automatically and rotated
  # on demand via the console or aws rds rotate-secret CLI.
  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.rds.arn

  # Storage
  storage_type          = "gp3"
  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.rds.arn

  # Network
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.rds_sg_id]
  publicly_accessible    = false

  # HA
  multi_az = var.multi_az

  # Backups
  backup_retention_period   = 7
  backup_window             = "03:00-04:00"
  maintenance_window        = "Mon:04:00-Mon:05:00"
  copy_tags_to_snapshot     = true
  delete_automated_backups  = false
  skip_final_snapshot       = false
  final_snapshot_identifier = "${lower(var.project)}-${var.environment}-final-snapshot"

  # Parameter group
  parameter_group_name = aws_db_parameter_group.this.name

  # Monitoring
  monitoring_interval                   = 60
  monitoring_role_arn                   = aws_iam_role.rds_enhanced_monitoring.arn
  enabled_cloudwatch_logs_exports       = ["postgresql", "upgrade"]
  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  # Misc
  auto_minor_version_upgrade = true
  apply_immediately          = false
  deletion_protection        = var.environment == "production"

  tags = {
    Name = "${var.project}-${var.environment}-rds"
  }

  depends_on = [aws_db_parameter_group.this]

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
# Enhanced Monitoring IAM Role
# --------------------------------------------------------------------------

resource "aws_iam_role" "rds_enhanced_monitoring" {
  name = "${var.project}-${var.environment}-rds-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${var.project}-${var.environment}-rds-monitoring-role"
  }
}

resource "aws_iam_role_policy_attachment" "rds_enhanced_monitoring" {
  role       = aws_iam_role.rds_enhanced_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}
