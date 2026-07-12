# ============================================================================
# AETHER — enterprise-isolated deployment profile
# Apply: terraform apply -var-file=profiles/enterprise-isolated.tfvars
# Contractual/regulatory customer isolation. Dedicated VPC/Aurora/queues, HA
# NAT, larger capacity, customer-specific retention.
# ============================================================================

deployment_profile = "enterprise-isolated"

# Network — NAT per AZ; private connectivity assumed.
enable_nat_gateway_ha = true

# Aurora Serverless v2 — larger dedicated capacity.
aurora_min_acu = 2
aurora_max_acu = 16

# Database — Multi-AZ for isolation/durability guarantees.
db_multi_az = true

# Logs — longer retention for contractual/regulatory needs.
log_retention_days = 30
