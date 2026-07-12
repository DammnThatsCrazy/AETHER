# ============================================================================
# AETHER — production-scale deployment profile
# Apply: terraform apply -var-file=profiles/production-scale.tfvars
# Higher traffic once justified. May enable ElastiCache, MSK, Neptune,
# ClickHouse, dedicated ML, and controlled egress (NAT HA).
# ============================================================================

deployment_profile = "production-scale"

# Network — NAT per AZ for availability.
enable_nat_gateway_ha = true

# Aurora Serverless v2 — larger warm floor and ceiling.
aurora_min_acu = 1
aurora_max_acu = 8

# Logs — longer retention for higher-traffic diagnostics.
log_retention_days = 7
