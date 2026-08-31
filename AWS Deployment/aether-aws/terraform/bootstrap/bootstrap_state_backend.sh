#!/usr/bin/env bash
# =============================================================================
# AETHER — Terraform remote-state backend bootstrap
#
# Creates the ONE thing the live Terraform root cannot create for itself: the
# S3 bucket + DynamoDB lock table that hold its remote state. `versions.tf`
# declares `backend "s3" {}` with no inline config, and the promotion workflows
# inject bucket / lock-table / key / region at `terraform init` time. Those
# names must exist before the first init, so this script provisions them.
#
# It is idempotent: existing, correctly-configured resources are left alone.
# It provisions state plumbing ONLY — no VPC, no ECS, no data stores. Those are
# Terraform's job, driven by a deployment profile (see ../../SETUP.md).
#
# Usage:
#   ./bootstrap_state_backend.sh \
#     --bucket aether-tfstate-<account-id> \
#     --lock-table aether-tf-locks \
#     --region us-east-1
#
# The bucket/table names you choose here are exactly the values the promotion
# workflow reads from the TF_STATE_BUCKET and TF_LOCK_TABLE GitHub secrets.
#
# Requires: AWS CLI v2 with credentials for the TARGET account, and permission
# to create/administer the bucket and table. Run it once per AWS account.
# =============================================================================
set -euo pipefail

BUCKET=""
LOCK_TABLE="aether-tf-locks"
REGION="${AWS_REGION:-us-east-1}"
DRY_RUN=0

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --bucket)     BUCKET="${2:?--bucket needs a value}"; shift 2 ;;
    --lock-table) LOCK_TABLE="${2:?--lock-table needs a value}"; shift 2 ;;
    --region)     REGION="${2:?--region needs a value}"; shift 2 ;;
    --dry-run)    DRY_RUN=1; shift ;;
    -h|--help)    usage 0 ;;
    *) echo "Unknown argument: $1" >&2; usage 1 ;;
  esac
done

if [ -z "$BUCKET" ]; then
  echo "ERROR: --bucket is required (e.g. aether-tfstate-\$(aws sts get-caller-identity --query Account --output text))" >&2
  usage 1
fi

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY-RUN: $*"
  else
    "$@"
  fi
}

command -v aws >/dev/null 2>&1 || { echo "ERROR: AWS CLI not found on PATH." >&2; exit 1; }

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
echo "==> Target account : ${ACCOUNT_ID}"
echo "==> Region         : ${REGION}"
echo "==> State bucket    : ${BUCKET}"
echo "==> Lock table      : ${LOCK_TABLE}"
echo

# --- S3 state bucket ---------------------------------------------------------
echo "==> [1/5] S3 bucket"
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "    bucket already exists — leaving in place"
else
  if [ "$REGION" = "us-east-1" ]; then
    run aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    run aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration "LocationConstraint=${REGION}"
  fi
  echo "    created"
fi

echo "==> [2/5] Bucket versioning (state history / recovery)"
run aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

echo "==> [3/5] Default encryption (SSE, AES256)"
run aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'

echo "==> [4/5] Block ALL public access"
run aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# --- DynamoDB lock table -----------------------------------------------------
echo "==> [5/5] DynamoDB lock table"
if aws dynamodb describe-table --table-name "$LOCK_TABLE" --region "$REGION" >/dev/null 2>&1; then
  echo "    table already exists — leaving in place"
else
  run aws dynamodb create-table \
    --table-name "$LOCK_TABLE" \
    --region "$REGION" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST
  if [ "$DRY_RUN" -eq 0 ]; then
    echo "    waiting for table to become ACTIVE..."
    aws dynamodb wait table-exists --table-name "$LOCK_TABLE" --region "$REGION"
  fi
  echo "    created"
fi

cat <<EOF

=============================================================================
State backend ready.

Wire these into CI (per-profile GitHub environments used by
.github/workflows/terraform-promote.yml):

  TF_STATE_BUCKET = ${BUCKET}
  TF_LOCK_TABLE   = ${LOCK_TABLE}
  AWS_REGION      = ${REGION}

For a LOCAL init against this backend (plan-only; applies go through the
reviewed promotion workflow):

  cd "AWS Deployment/aether-aws/terraform"
  terraform init \\
    -backend-config="bucket=${BUCKET}" \\
    -backend-config="dynamodb_table=${LOCK_TABLE}" \\
    -backend-config="key=profiles/staging/terraform.tfstate" \\
    -backend-config="region=${REGION}" \\
    -backend-config="encrypt=true"

Next: follow AWS Deployment/aether-aws/SETUP.md from "Step 3".
=============================================================================
EOF
