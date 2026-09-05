# ============================================================================
# AETHER — staging deployment profile
# Apply: terraform apply -var-file=profiles/staging.tfvars
# Release rehearsal. Wake for validation, sleep after — cost capped.
# ============================================================================

deployment_profile = "staging"

# The immutable backend registry was created by the release pipeline before
# Terraform state ownership. Reconcile it without replacement: ECR encryption
# cannot be changed after creation. Other staging repositories remain KMS.
ecr_repository_encryption_types = {
  aether-backend = "AES256"
}
ecr_repository_tag_mutabilities = {
  aether-backend = "IMMUTABLE"
}

# Root default is production — staging must say so explicitly.
environment = "staging"

# Network — no NAT Gateway at all. Rehearsal traffic egresses via a public IP
# on the task ENI, so staging pays nothing for NAT while it is awake.
network_egress_mode = "public_ip"

# Aurora Serverless v2 — auto-pause when idle (min ACU 0).
aurora_min_acu = 0
aurora_max_acu = 2
# The AWS account's free-tier guard permits one day of automated Aurora
# backups. Longer retention is reserved for paid production profiles.
aurora_backup_retention_days = 1
# Express mode uses AWS-managed encryption instead of a customer-managed KMS
# key, which is required for AWS Free-tier accounts.
aurora_express_mode = true
# AWS Free-tier accounts require WithExpressConfiguration for Aurora, which
# forces Internet Access Gateway mode (no VPC). Skip Aurora until the account
# is upgraded; the rest of the stack validates without it.
skip_aurora = true

# Logs — short retention; INFO/DEBUG ship to S3.
log_retention_days        = 3
enable_social_connections = false
