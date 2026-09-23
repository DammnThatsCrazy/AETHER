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
# The account is paid, so full staging uses the customer-managed Aurora KMS
# key and exercises the same encrypted database topology that production-lean
# will receive. The bounded Serverless v2 profile still auto-pauses while idle.
aurora_express_mode = false
skip_aurora         = false

# The staging custom-domain associations already exist and are verified in
# Amplify, with Squarespace remaining authoritative for DNS. Keep Terraform
# aligned with those live associations and use the staging API health origin
# for the status shell; state reconciliation imports the existing associations
# before a reviewed plan is created.
amplify_custom_domain_enabled = true
amplify_domain_name           = "staging.olympuslabsml.com"
status_api_url                = "https://api.staging.olympuslabsml.com/health"

# Logs — short retention; INFO/DEBUG ship to S3.
log_retention_days        = 3
enable_social_connections = false
