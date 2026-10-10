# ============================================================================
# AETHER — Neptune (Graph DB) Module
#
# Provisions a Neptune cluster with:
#   - KMS encryption at rest
#   - IAM auth enabled
#   - Cluster instances spread across AZs
#   - Automated backups (7 days)
#
# IMPORTANT — See README.md for connectivity details.
# Neptune is VPC-only. Access from ECS tasks via private subnet.
# ============================================================================

data "aws_region" "current" {}

# --------------------------------------------------------------------------
# KMS Key
# --------------------------------------------------------------------------

resource "aws_kms_key" "neptune" {
  description             = "${var.project} Neptune encryption key (${var.environment})"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = {
    Name = "${var.project}-${var.environment}-neptune-kms"
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

resource "aws_kms_alias" "neptune" {
  name          = "alias/${lower(var.project)}-${var.environment}-neptune"
  target_key_id = aws_kms_key.neptune.key_id
}

# --------------------------------------------------------------------------
# Subnet Group
# --------------------------------------------------------------------------

resource "aws_neptune_subnet_group" "this" {
  name       = "${lower(var.project)}-${var.environment}-neptune"
  subnet_ids = var.subnet_ids

  tags = {
    Name = "${var.project}-${var.environment}-neptune-subnet-group"
  }
}

# --------------------------------------------------------------------------
# Parameter Group
# --------------------------------------------------------------------------

resource "aws_neptune_parameter_group" "this" {
  name_prefix = "${lower(var.project)}-${var.environment}-neptune-"
  family      = "neptune1.3"
  description = "${var.project} ${var.environment} Neptune parameters"

  parameter {
    name         = "neptune_enable_audit_log"
    value        = "1"
    apply_method = "pending-reboot"
  }

  tags = {
    Name = "${var.project}-${var.environment}-neptune-pg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# --------------------------------------------------------------------------
# Cluster Parameter Group
# --------------------------------------------------------------------------

resource "aws_neptune_cluster_parameter_group" "this" {
  name_prefix = "${lower(var.project)}-${var.environment}-neptune-cluster-"
  family      = "neptune1.3"
  description = "${var.project} ${var.environment} Neptune cluster parameters"

  parameter {
    name         = "neptune_enable_audit_log"
    value        = "1"
    apply_method = "pending-reboot"
  }

  tags = {
    Name = "${var.project}-${var.environment}-neptune-cluster-pg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# --------------------------------------------------------------------------
# Neptune Cluster
# --------------------------------------------------------------------------

resource "aws_neptune_cluster" "this" {
  cluster_identifier = "${lower(var.project)}-${var.environment}-neptune"
  engine             = "neptune"
  engine_version     = "1.3.0.0"

  neptune_subnet_group_name            = aws_neptune_subnet_group.this.name
  vpc_security_group_ids               = [var.neptune_sg_id]
  neptune_cluster_parameter_group_name = aws_neptune_cluster_parameter_group.this.name

  # IAM authentication (no username/password)
  iam_database_authentication_enabled = true

  # Encryption
  storage_encrypted = true
  kms_key_arn       = aws_kms_key.neptune.arn

  # Backups
  backup_retention_period = 7
  preferred_backup_window = "03:00-04:00"

  # Ports
  port = 8182

  # Protection
  deletion_protection       = var.environment == "production"
  skip_final_snapshot       = false
  final_snapshot_identifier = "${lower(var.project)}-${var.environment}-neptune-final"

  tags = {
    Name = "${var.project}-${var.environment}-neptune"
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
# Cluster Instances (writer first, then readers)
# --------------------------------------------------------------------------

resource "aws_neptune_cluster_instance" "this" {
  count = var.cluster_size

  identifier         = "${lower(var.project)}-${var.environment}-neptune-${count.index}"
  cluster_identifier = aws_neptune_cluster.this.id
  instance_class     = var.instance_class
  engine             = "neptune"

  neptune_parameter_group_name = aws_neptune_parameter_group.this.name
  publicly_accessible          = false
  auto_minor_version_upgrade   = true

  tags = {
    Name = "${var.project}-${var.environment}-neptune-${count.index == 0 ? "writer" : "reader-${count.index}"}"
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
