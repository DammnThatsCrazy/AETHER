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

# staging.olympuslabsml.com is a Route 53 zone (created outside this root,
# delegated from Squarespace by NS records). Terraform owns its records: the
# Amplify subdomains, api, and the certificate validation CNAMEs below, which
# mirror what Squarespace served before delegation.
product_dns_zone_id = "Z01866633FQOV3YDH5J11"
product_dns_validation_cnames = {
  # Amplify-managed certificate for the staging custom domain.
  "_0d97b787857def1c3cc9147d86786335" = "_fa41a8638b50a07ba696b82c152f2460.wzccmgtwzk.acm-validations.aws."
  # ACM certificate on the staging ALB (app, api and kyber names).
  "_91e89497e944d212307cabe5d75ff5ff.app"   = "_210138834ca1a798d03f86ae35dfd480.jkddzztszm.acm-validations.aws."
  "_a9bef454d149a285497e23319ef4863b.api"   = "_9ce54274a5435ae118abb366b269a9de.jkddzztszm.acm-validations.aws."
  "_f65ab0075246880067ce04c5c74ab348.kyber" = "_ea98898bcc26d2f4924259ab2fe79486.jkddzztszm.acm-validations.aws."
}

# Logs — short retention; INFO/DEBUG ship to S3.
log_retention_days        = 3
enable_social_connections = false

# Per-PR previews of the Aether app (frontend-preview.yml): an unconnected
# Amplify app whose pr-<N> branches call this staging API and Auth0.
enable_frontend_previews = true
