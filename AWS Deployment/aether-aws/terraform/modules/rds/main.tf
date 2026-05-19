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
# Random password (stored in Secrets Manager by the secrets module)
# We generate it here so it can be seeded into the DB and the secret value.
# --------------------------------------------------------------------------

resource "random_password" "db" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}:?"
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id = var.db_password_secret_arn
  secret_string = jsonencode({
    username = "aether_admin"
    password = random_password.db.result
    engine   = "postgres"
    host     = aws_db_instance.this.address
    port     = aws_db_instance.this.port
    dbname   = var.db_name
  })
}

# --------------------------------------------------------------------------
# RDS Instance
# --------------------------------------------------------------------------

resource "aws_db_instance" "this" {
  identifier = "${lower(var.project)}-${var.environment}-postgres"

  engine               = "postgres"
  engine_version       = "16"
  instance_class       = var.db_instance_class
  db_name              = var.db_name
  username             = "aether_admin"
  password             = random_password.db.result
  port                 = 5432

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
  monitoring_interval             = 60
  monitoring_role_arn             = aws_iam_role.rds_enhanced_monitoring.arn
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
  performance_insights_enabled    = true
  performance_insights_retention_period = 7

  # Misc
  auto_minor_version_upgrade  = true
  apply_immediately           = false
  deletion_protection         = var.environment == "production"

  tags = {
    Name = "${var.project}-${var.environment}-rds"
  }

  depends_on = [aws_db_parameter_group.this]
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
