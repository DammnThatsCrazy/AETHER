# ============================================================================
# AETHER — MSK (Managed Streaming for Kafka) Module
#
# Provisions a 3-broker MSK cluster with:
#   - Kafka 3.x
#   - TLS encryption in-transit
#   - KMS encryption at rest
#   - Broker nodes spread across 3 AZs
#   - CloudWatch metrics enabled
# ============================================================================

data "aws_region" "current" {}

# --------------------------------------------------------------------------
# KMS Key for MSK storage encryption
# --------------------------------------------------------------------------

resource "aws_kms_key" "msk" {
  description             = "${var.project} MSK encryption key (${var.environment})"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = {
    Name = "${var.project}-${var.environment}-msk-kms"
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

resource "aws_kms_alias" "msk" {
  name          = "alias/${lower(var.project)}-${var.environment}-msk"
  target_key_id = aws_kms_key.msk.key_id
}

# --------------------------------------------------------------------------
# CloudWatch Log Group for MSK broker logs
# --------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "msk_broker" {
  name              = "/aws/msk/${var.project}-${var.environment}/broker"
  retention_in_days = 30

  tags = {
    Name = "${var.project}-${var.environment}-msk-broker-logs"
  }
}

# --------------------------------------------------------------------------
# MSK Configuration
# --------------------------------------------------------------------------

resource "aws_msk_configuration" "this" {
  name           = "${lower(var.project)}-${var.environment}-kafka-config"
  kafka_versions = [var.kafka_version]
  description    = "${var.project} ${var.environment} Kafka configuration"

  server_properties = <<-EOF
    auto.create.topics.enable=false
    delete.topic.enable=true
    log.retention.hours=168
    num.partitions=3
    default.replication.factor=3
    min.insync.replicas=2
    compression.type=lz4
  EOF
}

# --------------------------------------------------------------------------
# MSK Cluster
# --------------------------------------------------------------------------

resource "aws_msk_cluster" "this" {
  cluster_name           = "${lower(var.project)}-${var.environment}-kafka"
  kafka_version          = var.kafka_version
  number_of_broker_nodes = var.broker_count

  broker_node_group_info {
    instance_type   = var.broker_instance_type
    client_subnets  = var.subnet_ids
    security_groups = [var.msk_sg_id]

    storage_info {
      ebs_storage_info {
        volume_size = var.broker_volume_size
      }
    }
  }

  configuration_info {
    arn      = aws_msk_configuration.this.arn
    revision = aws_msk_configuration.this.latest_revision
  }

  encryption_info {
    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
    encryption_at_rest_kms_key_arn = aws_kms_key.msk.arn
  }

  client_authentication {
    unauthenticated = false
    tls {}
  }

  open_monitoring {
    prometheus {
      jmx_exporter {
        enabled_in_broker = true
      }
      node_exporter {
        enabled_in_broker = true
      }
    }
  }

  logging_info {
    broker_logs {
      cloudwatch_logs {
        enabled   = true
        log_group = aws_cloudwatch_log_group.msk_broker.name
      }
    }
  }

  enhanced_monitoring = "PER_TOPIC_PER_BROKER"

  tags = {
    Name = "${var.project}-${var.environment}-msk"
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
