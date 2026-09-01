# ============================================================================
# AETHER — production-lean deployment profile (founding-tenant target)
# Apply: terraform apply -var-file=profiles/production-lean.tfvars
#
# First customer / early controlled production. Forbidden resources (MSK,
# ElastiCache, Neptune, ClickHouse, dedicated ML, frontend ECS, legacy RDS,
# always-on NAT, always-on staging compute, Prometheus/Grafana) MUST NOT be
# provisioned — see config/deployment_profiles.yaml and profiles.tf.
# ============================================================================

deployment_profile = "production-lean"

# Network — no NAT Gateway. NAT is forbidden-unless-explicit for this profile;
# changing this value to single_nat or ha_nat IS the explicit opt-in, and must
# be reviewed as a cost-policy exception.
network_egress_mode = "public_ip"

# Aurora Serverless v2 — always warm at a small floor.
aurora_min_acu = 0.5
aurora_max_acu = 4

# Logs — short CloudWatch retention; bulk logs to S3.
log_retention_days = 3


# ==============================================================================
# tfmcp — Terraform MCP Server (opt-in)
# ============================================================================
# Set enable_tfmcp_in_lean = true to deploy the tfmcp MCP server on the
# production-lean profile. Required before applying:
#   1. Build and push the image: ./AWS\ Deployment/aether-aws/build-tfmcp.sh
#   2. Pin the digest below (sha256:...)
#   3. Run the reviewed promotion workflow (.github/workflows/terraform-promote.yml)
#
# Cost: one Fargate task at 512 CPU / 1024 MiB is ~$7-15/month. Re-run the
# cost model before applying to confirm the total stays within the profile
# budget (config/deployment_profiles.yaml).
# ============================================================================

enable_tfmcp_in_lean  = true
tfmcp_image_digest    = ""  # set after build: "sha256:..."
tfmcp_auth_token      = ""  # auto-generated if empty (32+ chars)
tfmcp_github_pat      = ""  # set if Aether repo is private
