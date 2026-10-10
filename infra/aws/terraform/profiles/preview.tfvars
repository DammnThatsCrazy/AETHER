# ============================================================================
# AETHER — preview deployment profile
# Apply: terraform apply -var-file=profiles/preview.tfvars
# PR-specific live environment, only when explicitly requested. Ephemeral-class:
# cost capped, TTL-cleanup required, auto-expire, never NAT egress.
# ============================================================================

deployment_profile = "preview"

# Root default is production — preview must say so explicitly.
environment = "preview"

# Network — no NAT Gateway at all. Preview traffic egresses via a public IP on
# the task ENI, so preview pays nothing for NAT while it is awake.
network_egress_mode = "public_ip"

# Aurora Serverless v2 — auto-pause when idle (min ACU 0).
aurora_min_acu = 0
aurora_max_acu = 2

# Logs — short retention; INFO/DEBUG ship to S3.
log_retention_days = 3
