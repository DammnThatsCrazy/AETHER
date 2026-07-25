# ============================================================================
# AETHER — staging deployment profile
# Apply: terraform apply -var-file=profiles/staging.tfvars
# Release rehearsal. Wake for validation, sleep after — cost capped.
# ============================================================================

deployment_profile = "staging"

# Root default is production — staging must say so explicitly.
environment = "staging"

# Network — no NAT Gateway at all. Rehearsal traffic egresses via a public IP
# on the task ENI, so staging pays nothing for NAT while it is awake.
network_egress_mode = "public_ip"

# Aurora Serverless v2 — auto-pause when idle (min ACU 0).
aurora_min_acu = 0
aurora_max_acu = 2

# Logs — short retention; INFO/DEBUG ship to S3.
log_retention_days = 3
