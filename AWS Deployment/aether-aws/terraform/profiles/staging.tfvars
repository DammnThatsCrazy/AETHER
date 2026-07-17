# ============================================================================
# AETHER — staging deployment profile
# Apply: terraform apply -var-file=profiles/staging.tfvars
# Release rehearsal. Wake for validation, sleep after — cost capped.
# ============================================================================

deployment_profile = "staging"

# Root default is production — staging must say so explicitly.
environment = "staging"

# Network — single shared NAT, no HA (cost).
enable_nat_gateway_ha = false

# Aurora Serverless v2 — auto-pause when idle (min ACU 0).
aurora_min_acu = 0
aurora_max_acu = 2

# Logs — short retention; INFO/DEBUG ship to S3.
log_retention_days = 3
