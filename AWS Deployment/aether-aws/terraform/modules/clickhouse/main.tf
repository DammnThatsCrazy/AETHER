# ============================================================================
# AETHER — ClickHouse Analytics Module
#
# Self-managed ClickHouse on a single EC2 appliance with a dedicated EBS data
# volume, for the analytics backend the production-scale / enterprise-isolated
# profiles declare (`analytics: clickhouse` in config/deployment_profiles.yaml).
#
# This is the provisioning counterpart to local.analytics_backend == "clickhouse"
# in profiles.tf: that selector is only honest once a ClickHouse host exists to
# connect to. The runtime consumes it through CLICKHOUSE_HOST / CLICKHOUSE_PORT
# (see shared/cis/clickhouse.py and scripts/validate_infra.py, which require
# CLICKHOUSE_HOST when a profile declares analytics: clickhouse).
#
# The resource NAMES below deliberately begin with `clickhouse`: the plan-policy
# contract (config/terraform_resource_contracts.yaml, canonical key `clickhouse`)
# matches aws_instance / aws_ebs_volume instances by name_prefix so the scale
# plan attributes this appliance to the clickhouse key instead of reporting it
# as an uncontracted expensive resource.
#
# AWS has no managed ClickHouse service, so "self-managed on EC2 + EBS" is the
# additive, planable-offline shape the contract anticipates (its comment names
# aws_instance/aws_ebs_volume as "the storage half of the same decision").
#
# DECOMMISSION.md posture: the appliance and its disk carry
# lifecycle.prevent_destroy, so flipping a profile toggle off ClickHouse plans
# a hard error instead of an auto-destroy of analytics state. Retiring the box
# for real goes through the documented release-from-state procedure.
# ============================================================================

data "aws_region" "current" {}

# --------------------------------------------------------------------------
# Security group — the analytics box speaks native TCP 9000 and HTTP 8123
# to the ECS task security group only. No public CIDR ingress by default.
# --------------------------------------------------------------------------

resource "aws_security_group" "clickhouse" {
  name_prefix = "clickhouse-${var.project}-${var.environment}-"
  description = "ClickHouse analytics access (native TCP 9000, HTTP 8123)"
  vpc_id      = var.vpc_id

  tags = {
    Name = "clickhouse-${var.project}-${var.environment}"
  }
}

resource "aws_security_group_rule" "clickhouse_native" {
  type                     = "ingress"
  from_port                = 9000
  to_port                  = 9000
  protocol                 = "tcp"
  security_group_id        = aws_security_group.clickhouse.id
  source_security_group_id = var.allowed_sg_id
  description              = "ClickHouse native protocol from ECS tasks"
}

resource "aws_security_group_rule" "clickhouse_http" {
  type                     = "ingress"
  from_port                = 8123
  to_port                  = 8123
  protocol                 = "tcp"
  security_group_id        = aws_security_group.clickhouse.id
  source_security_group_id = var.allowed_sg_id
  description              = "ClickHouse HTTP interface from ECS tasks"
}

resource "aws_security_group_rule" "clickhouse_egress" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.clickhouse.id
  description       = "ClickHouse package/network egress"
}

# --------------------------------------------------------------------------
# The appliance and its data volume
# --------------------------------------------------------------------------

resource "aws_instance" "clickhouse" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.clickhouse.id]
  key_name               = var.key_name
  user_data              = base64encode(local.user_data)

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size
    encrypted   = true
  }

  tags = {
    Name = "clickhouse-${var.project}-${var.environment}"
  }

  lifecycle {
    # Stateful analytics appliance: profile toggles must never auto-destroy it.
    prevent_destroy = true
  }
}

resource "aws_ebs_volume" "clickhouse_data" {
  availability_zone = aws_instance.clickhouse.availability_zone
  size              = var.data_volume_size
  type              = var.data_volume_type
  encrypted         = true

  tags = {
    Name = "clickhouse-${var.project}-${var.environment}-data"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# The legacy aws_volume_attachment name is used (not aws_ebs_volume_attachment)
# because the offline-locked AWS provider build used for plan validation does not
# expose the newer alias; both resolve to the same EC2 AttachVolume API and this
# root pins ~> 5.0, which ships both. skip_destroy is false so the disk detaches
# but survives a drive replacement, while the volume itself stays
# prevent_destroy.
resource "aws_volume_attachment" "clickhouse_data_attach" {
  device_name  = "/dev/sdf"
  volume_id    = aws_ebs_volume.clickhouse_data.id
  instance_id  = aws_instance.clickhouse.id
  skip_destroy = false
}

# --------------------------------------------------------------------------
# CloudWatch log group — the box ships broker/query logs here for retention.
# (The CloudWatch agent is installed by user_data; the group is created here so
# retention policy is Terraform-owned.)
# --------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "clickhouse" {
  name              = "/aether/${var.project}-${var.environment}/clickhouse"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "clickhouse-${var.project}-${var.environment}-logs"
  }
}

# --------------------------------------------------------------------------
# Bootstrap — install ClickHouse from the official RPM repo and mount the data
# volume at /var/lib/clickhouse. Idempotent: safe to re-run on reboot.
# --------------------------------------------------------------------------

locals {
  user_data = <<-EOT
    #!/usr/bin/env bash
    set -euo pipefail

    # Install ClickHouse from the official repository (Amazon Linux 2023 / dnf).
    if [ ! -f /etc/yum.repos.d/clickhouse.repo ]; then
      curl -fsSL https://packages.clickhouse.com/rpm/clickhouse.repo -o /etc/yum.repos.d/clickhouse.repo
    fi
    dnf install -y clickhouse-server clickhouse-client

    # Mount the dedicated data volume at /var/lib/clickhouse (Nitro maps
    # /dev/sdf to a /dev/nvme* node; pick the first non-root block device).
    DATA_DEV=$(lsblk -dnp -o NAME | grep -E 'nvme[0-9]+n[0-9]+|sd[b-z]$' | head -1 || true)
    if [ -n "$${DATA_DEV}" ]; then
      if ! blkid "$${DATA_DEV}" >/dev/null 2>&1; then
        mkfs.xfs "$${DATA_DEV}"
      fi
      mkdir -p /var/lib/clickhouse
      if ! mountpoint -q /var/lib/clickhouse; then
        mount "$${DATA_DEV}" /var/lib/clickhouse
      fi
      grep -q "$${DATA_DEV} /var/lib/clickhouse" /etc/fstab || \
        echo "$${DATA_DEV} /var/lib/clickhouse xfs defaults 0 2" >> /etc/fstab
    fi

    chown -R clickhouse:clickhouse /var/lib/clickhouse
    systemctl enable --now clickhouse-server

    # Best-effort CloudWatch agent for broker/query logs. Missing the install
    # must not block ClickHouse from coming up.
    dnf install -y amazon-cloudwatch-agent || true
    if [ -x /usr/bin/amazon-cloudwatch-agent-ctl ]; then
      cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<'JSON'
    {
      "logs": {
        "logs_collected": {
          "files": {
            "collect_list": [
              { "file_path": "/var/log/clickhouse-server/clickhouse-server.log",
                "log_group_name": "/aether/${var.project}-${var.environment}/clickhouse",
                "log_stream_name": "{instance_id}",
                "timestamp_format": "%Y.%m.%d %H:%M:%S" }
            ]
          }
        }
      }
    }
    JSON
      /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
        -a fetch-config -m ec2 -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json -s || true
    fi
  EOT
}
