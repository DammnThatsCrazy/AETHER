# ============================================================================
# AETHER — Aurora Serverless v2 Module (E3 cost reduction)
#
# Provisions Aurora PostgreSQL 16 in Serverless v2 mode:
#   - Prod:    min_acu=0.5 (stays warm), max_acu=4
#   - Staging: min_acu=0   (auto-pause after ~5 min idle), max_acu=2
#
# Pay-per-ACU-second; no always-on instance cost vs. RDS Multi-AZ.
# Cold-start after long idle: ~15-30 s on staging; prod stays warm at 0.5 ACU.
# ============================================================================

data "aws_region" "current" {}

# --------------------------------------------------------------------------
# KMS Key (skipped in express mode — uses AWS-managed default encryption)
# --------------------------------------------------------------------------

resource "aws_kms_key" "aurora" {
  count                   = var.express_mode ? 0 : 1
  description             = "${var.project} Aurora encryption key (${var.environment})"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = {
    Name        = "${var.project}-${var.environment}-aurora-kms"
    Environment = var.environment
  }
}

resource "aws_kms_alias" "aurora" {
  count         = var.express_mode ? 0 : 1
  name          = "alias/${lower(var.project)}-${var.environment}-aurora"
  target_key_id = aws_kms_key.aurora[0].key_id
}

# --------------------------------------------------------------------------
# Subnet Group
# --------------------------------------------------------------------------

resource "aws_db_subnet_group" "aurora" {
  name       = "${lower(var.project)}-${var.environment}-aurora"
  subnet_ids = var.subnet_ids

  tags = {
    Name = "${var.project}-${var.environment}-aurora-subnet-group"
  }
}

# --------------------------------------------------------------------------
# Cluster Parameter Group (Aurora PostgreSQL 16)
# --------------------------------------------------------------------------

resource "aws_rds_cluster_parameter_group" "this" {
  name_prefix = "${lower(var.project)}-${var.environment}-aurora16-"
  family      = "aurora-postgresql16"
  description = "${var.project} ${var.environment} Aurora PostgreSQL 16 parameters"

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
    Name = "${var.project}-${var.environment}-aurora-pg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# --------------------------------------------------------------------------
# Aurora Serverless v2 Cluster
# --------------------------------------------------------------------------

resource "aws_rds_cluster" "this" {
  cluster_identifier = "${lower(var.project)}-${var.environment}-aurora"

  engine         = "aurora-postgresql"
  engine_version = "16.4"
  engine_mode    = "provisioned"

  database_name   = var.db_name
  master_username = "aether_admin"
  port            = 5432

  # AWS manages the master password — never stored in Terraform state.
  manage_master_user_password   = true
  master_user_secret_kms_key_id = var.express_mode ? null : aws_kms_key.aurora[0].arn

  # Serverless v2 scaling — min=0 enables auto-pause (staging); min=0.5 keeps warm (prod).
  serverlessv2_scaling_configuration {
    min_capacity             = var.min_acu
    max_capacity             = var.max_acu
    seconds_until_auto_pause = var.auto_pause_seconds
  }

  # Storage
  storage_encrypted = true
  kms_key_id        = var.express_mode ? null : aws_kms_key.aurora[0].arn

  # Network
  db_subnet_group_name   = aws_db_subnet_group.aurora.name
  vpc_security_group_ids = [var.aurora_sg_id]

  # Backups
  backup_retention_period   = var.backup_retention_days
  preferred_backup_window   = "03:00-04:00"
  copy_tags_to_snapshot     = true
  skip_final_snapshot       = var.environment != "production"
  final_snapshot_identifier = var.environment == "production" ? "${lower(var.project)}-${var.environment}-final-snapshot" : null

  # Parameter group
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.this.name

  # Logging
  enabled_cloudwatch_logs_exports = ["postgresql"]

  deletion_protection = var.deletion_protection
  apply_immediately   = var.environment != "production"

  tags = {
    Name = "${var.project}-${var.environment}-aurora"
  }

  depends_on = [aws_rds_cluster_parameter_group.this]
}

# --------------------------------------------------------------------------
# Aurora Serverless v2 Instance (one writer; storage HA is Aurora-native)
# --------------------------------------------------------------------------

resource "aws_rds_cluster_instance" "writer" {
  identifier         = "${lower(var.project)}-${var.environment}-aurora-writer"
  cluster_identifier = aws_rds_cluster.this.id

  instance_class = "db.serverless"
  engine         = aws_rds_cluster.this.engine
  engine_version = aws_rds_cluster.this.engine_version

  # Enhanced Monitoring (60 s granularity)
  monitoring_interval = 60
  monitoring_role_arn = aws_iam_role.aurora_enhanced_monitoring.arn

  performance_insights_enabled          = true
  performance_insights_retention_period = 7
  performance_insights_kms_key_id       = var.express_mode ? null : aws_kms_key.aurora[0].arn

  auto_minor_version_upgrade = true
  apply_immediately          = var.environment != "production"

  tags = {
    Name = "${var.project}-${var.environment}-aurora-writer"
  }
}

# --------------------------------------------------------------------------
# Enhanced Monitoring IAM Role
# --------------------------------------------------------------------------

resource "aws_iam_role" "aurora_enhanced_monitoring" {
  name = "${var.project}-${var.environment}-aurora-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${var.project}-${var.environment}-aurora-monitoring-role"
  }
}

resource "aws_iam_role_policy_attachment" "aurora_enhanced_monitoring" {
  role       = aws_iam_role.aurora_enhanced_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}
