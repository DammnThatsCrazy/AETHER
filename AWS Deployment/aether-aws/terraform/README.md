# AETHER — Terraform Infrastructure

Production-grade AWS infrastructure for the AETHER platform, managed with Terraform.

## Architecture

```
Internet
   │
   └── ALB (public subnets, HTTPS with ACM cert)
          │
          ├── /v1/ml/* ──► ECS aether-ml-serving (private subnets, port 8080)
          │
          └── * ──────────► ECS aether-backend    (private subnets, port 8000)
                                  │
                                  ├── RDS Postgres 16    (isolated subnets)
                                  ├── ElastiCache Redis  (isolated subnets)
                                  ├── MSK Kafka          (isolated subnets)
                                  └── Neptune            (isolated subnets)
```

All secrets are fetched at container start-up from Secrets Manager. No secret
values appear in Terraform state or task definitions.

## Module Summary

| Module | Resources |
|--------|-----------|
| `vpc` | VPC, 3-tier subnets (public/private/isolated), NAT GW, security groups, flow logs |
| `ecr` | 4 private ECR repositories with lifecycle policies |
| `secrets` | 8 Secrets Manager stubs (KMS-encrypted, values injected post-deploy) |
| `rds` | RDS Postgres 16, Multi-AZ, KMS, enhanced monitoring |
| `elasticache` | Redis 7.x cluster, TLS, KMS |
| `msk` | 3-broker MSK Kafka, TLS, KMS, CloudWatch metrics |
| `neptune` | Neptune cluster + instances, IAM auth, KMS — VPC only |
| `alb` | Internet-facing ALB, HTTP→HTTPS redirect, path routing |
| `ecs` | Fargate cluster, 2 services, IAM roles, auto-scaling |
| `monitoring` | SNS alerts, 8 CloudWatch alarms, dashboard |

## Prerequisites

- **AWS CLI** >= 2.x, configured with credentials that have admin-level
  permissions (or a scoped IAM role for the account).
- **Terraform** >= 1.5.
- An ACM certificate in the target region for your domain name.
- An S3 bucket + DynamoDB table for Terraform remote state
  (if using the example backend configuration).

## Initialization

```bash
cd "AWS Deployment/aether-aws/terraform"

# Copy and fill in your values
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars

# Initialize providers and modules
terraform init

# Review what will be created
terraform plan -out=tfplan

# Apply (takes ~20 minutes on first run)
terraform apply tfplan
```

## Deployment Sequence

Terraform handles dependency ordering automatically. The high-level sequence is:

1. **VPC** — network foundation (subnets, NAT, security groups)
2. **ECR** — container registries (no images yet)
3. **Secrets** — secret stubs created in Secrets Manager
4. **RDS / ElastiCache / MSK / Neptune** — data stores
5. **ALB** — load balancer and target groups
6. **ECS** — Fargate cluster, task definitions, services (tasks start with `latest` image tag — services will stabilise once images are pushed)
7. **Monitoring** — alarms, SNS, dashboard

## Post-Deploy Steps

### 1. Confirm SNS email subscription

AWS sends a confirmation email to `alert_email`. Click the confirmation link
before alarms will deliver notifications.

### 2. Inject secret values

The Secrets Manager stubs are created empty. Populate them:

```bash
# JWT signing key (generate a secure random value)
aws secretsmanager put-secret-value \
  --secret-id aether/jwt-secret \
  --secret-string '{"value":"REPLACE_WITH_SECURE_RANDOM_256BIT_KEY"}'

# Stripe keys
aws secretsmanager put-secret-value \
  --secret-id aether/stripe-secret-key \
  --secret-string '{"value":"sk_live_..."}'

aws secretsmanager put-secret-value \
  --secret-id aether/stripe-webhook-secret \
  --secret-string '{"value":"whsec_..."}'

# BYOK encryption key, oracle signer, watermark key, canary seed
# (follow the same pattern for each secret listed in modules/secrets/main.tf)
```

The `aether/db-password` secret is populated automatically by the RDS module
and contains JSON with `host`, `port`, `username`, `password`, `dbname`.

### 3. Build and push Docker images

```bash
# Authenticate to ECR
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1

aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin \
  "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Build and push backend
docker build -t aether-backend ./backend
docker tag aether-backend:latest \
  "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/aether-backend:latest"
docker push \
  "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/aether-backend:latest"

# Build and push ml-serving
docker build -t aether-ml-serving ./ml-serving
docker tag aether-ml-serving:latest \
  "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/aether-ml-serving:latest"
docker push \
  "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/aether-ml-serving:latest"
```

### 4. Force ECS to pick up the new images

ECS services ignore image changes unless you trigger a new deployment:

```bash
aws ecs update-service \
  --cluster AETHER-production \
  --service AETHER-production-backend \
  --force-new-deployment

aws ecs update-service \
  --cluster AETHER-production \
  --service AETHER-production-ml-serving \
  --force-new-deployment
```

### 5. Run database migrations

Execute migrations from within the VPC (e.g. via ECS Exec, a bastion, or
a one-off Fargate task):

```bash
# Example using a one-off ECS task with your migration command
aws ecs run-task \
  --cluster AETHER-production \
  --task-definition AETHER-production-backend \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[...],securityGroups=[...],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"aether-backend","command":["python","-m","alembic","upgrade","head"]}]}'
```

## Outputs Reference

After `terraform apply`:

```bash
terraform output                  # show all outputs
terraform output -raw alb_dns     # ALB DNS name
terraform output ecr_urls         # ECR repository URLs
terraform output secret_arns      # Secrets Manager ARNs
```

Key outputs:

| Output | Description |
|--------|-------------|
| `alb_dns` | ALB DNS name — create a CNAME alias in Route 53 |
| `backend_url` | HTTPS URL derived from `domain_name` variable |
| `ecr_urls` | Map of service → ECR URL |
| `rds_endpoint` | RDS host address |
| `redis_endpoint` | Redis host:port |
| `kafka_brokers` | MSK TLS broker list |
| `neptune_endpoint` | Neptune writer endpoint |
| `secret_arns` | Map of secret name → ARN |
| `cloudwatch_dashboard_url` | Direct link to the CloudWatch dashboard |

## Tear-down

```bash
# Disable deletion protection on RDS and Neptune first
# (the resources have deletion_protection=true in production)
terraform apply -var 'environment=production' \
  -target=module.rds.aws_db_instance.this \
  ... # update deletion_protection to false

terraform destroy
```

## Security Notes

- No secret values are stored in Terraform state or code.
- All data stores are in isolated subnets with no default route.
- ECS tasks use dedicated IAM roles with least-privilege policies.
- The ALB enforces TLS 1.3 minimum with the `ELBSecurityPolicy-TLS13-1-2-2021-06` policy.
- VPC Flow Logs capture all traffic for audit purposes.
