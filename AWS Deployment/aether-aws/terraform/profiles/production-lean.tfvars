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
