# ============================================================================
# AETHER — production-scale deployment profile
# Apply: terraform apply -var-file=profiles/production-scale.tfvars
# Higher traffic once justified. May enable ElastiCache, MSK, Neptune,
# ClickHouse, dedicated ML, and controlled egress (single shared NAT).
# ============================================================================

deployment_profile = "production-scale"

# Network — one shared NAT Gateway. Private task subnets, controlled egress.
network_egress_mode = "single_nat"

# Aurora Serverless v2 — larger warm floor and ceiling.
aurora_min_acu = 1
aurora_max_acu = 8

# Logs — longer retention for higher-traffic diagnostics.
log_retention_days = 7
