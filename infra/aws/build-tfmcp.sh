#!/usr/bin/env bash
set -euo pipefail

TFMCP_VERSION="${TFMCP_VERSION:-0.2.2}"
AWS_ACCOUNT="${AWS_ACCOUNT:?AWS_ACCOUNT required — 12-digit AWS account ID}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ECR_REPO="aether-tfmcp"

ECR_URI="${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE="${ECR_URI}/${ECR_REPO}:${TFMCP_VERSION}"
IMAGE_LATEST="${ECR_URI}/${ECR_REPO}:latest"

echo "==> Building tfmcp v${TFMCP_VERSION}"

# NOTE: In the live root, the ECR repository is managed by
# terraform/modules/ecr/main.tf (aether-tfmcp). This standalone build script
# creates the repo if missing so the build can proceed without Terraform — for
# first-time build or local development only. In production, let Terraform own
# the repository lifecycle (encryption, scan-on-push, lifecycle policy, tags).
aws ecr describe-repositories \
  --repository-names "${ECR_REPO}" --region "${AWS_REGION}" \
  >/dev/null 2>&1 || {
  echo "    Creating ECR repository: ${ECR_REPO}"
  aws ecr create-repository \
    --repository-name "${ECR_REPO}" \
    --image-scanning-configuration scanOnPush=true \
    --region "${AWS_REGION}" >/dev/null
}

echo "    Logging in to ECR"
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_URI}"

echo "    Building image"
docker build \
  --build-arg TFMCP_VERSION="${TFMCP_VERSION}" \
  --build-arg TFMCP_REVISION="$(git rev-parse HEAD 2>/dev/null || echo 'unknown')" \
  --tag "${IMAGE}" --tag "${IMAGE_LATEST}" \
  -f Dockerfile.tfmcp .

echo "    Pushing ${IMAGE}"
docker push "${IMAGE}"
echo "    Pushing ${IMAGE_LATEST}"
docker push "${IMAGE_LATEST}"

echo ""
echo "==> Done. Image: ${IMAGE}"
echo "    Pin the sha256 digest in terraform.tfvars as tfmcp_image_digest"
