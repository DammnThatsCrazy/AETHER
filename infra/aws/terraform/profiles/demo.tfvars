# ============================================================================
# AETHER — demo deployment profile
# Apply: terraform apply -var-file=profiles/demo.tfvars
# Temporary live demo with an explicitly seeded backend tenant. Ephemeral-class:
# cost capped, TTL-cleanup required, never NAT egress.
# ============================================================================

deployment_profile = "demo"

# Root default is production — demo must say so explicitly.
environment = "demo"

# Network — no NAT Gateway at all. Demo traffic egresses via a public IP on the
# task ENI, so demo pays nothing for NAT while it is awake.
network_egress_mode = "public_ip"

# Aurora Serverless v2 — auto-pause when idle (min ACU 0).
aurora_min_acu = 0
aurora_max_acu = 2

# Logs — short retention; INFO/DEBUG ship to S3.
log_retention_days = 3
