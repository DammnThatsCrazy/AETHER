# ═══════════════════════════════════════════════════════════════════════════
# Aether — Shared Output Definitions
# Standard outputs across all environment compositions.
# ═══════════════════════════════════════════════════════════════════════════
#
# Usage: Each environment's main.tf defines its own outputs referencing
# module outputs. This file documents the standard output contract.
#
# Production outputs:
#   api_endpoint        - API Gateway HTTP API endpoint
#   ws_endpoint         - API Gateway WebSocket endpoint
#   cdn_domain          - CloudFront CDN domain
#   dashboard_domain    - CloudFront dashboard domain
#   alb_dns             - ALB DNS name
#   ecs_cluster         - ECS cluster name
#   rds_endpoint        - Aurora cluster endpoint
#   neptune_endpoint    - Neptune cluster endpoint
#   redis_endpoint      - ElastiCache configuration endpoint
#   kafka_brokers       - MSK bootstrap brokers (TLS)
#   opensearch_endpoint - OpenSearch domain endpoint
#   sagemaker_endpoint  - SageMaker inference endpoint name
#   vpc_id              - VPC ID
#   secrets_kms_key     - KMS key ARN for secrets
#   vpc_endpoints       - Map of VPC endpoint IDs
#
# Staging outputs (subset):
#   api_endpoint, ecs_cluster, rds_endpoint, vpc_id
#
# Dev outputs (minimal):
#   ecs_cluster, rds_endpoint, vpc_id
