#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../.." && pwd)"
repository_name="aether-access-mcp"

for tool in aws docker git; do
  command -v "$tool" >/dev/null 2>&1 || {
    printf 'Required command not found: %s\n' "$tool" >&2
    exit 1
  }
done

aws_region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
if [[ -z "$aws_region" ]]; then
  aws_region="$(aws configure get region 2>/dev/null || true)"
fi
if [[ -z "$aws_region" ]]; then
  printf 'Set AWS_REGION or configure an AWS CLI default region.\n' >&2
  exit 1
fi
docker buildx version >/dev/null 2>&1 || {
  printf 'Docker Buildx is required to publish the linux/amd64 image.\n' >&2
  exit 1
}

if [[ "$(git -C "$repo_root" rev-parse --is-inside-work-tree)" != "true" ]]; then
  printf 'The build context is not a Git worktree: %s\n' "$repo_root" >&2
  exit 1
fi

if [[ -n "$(git -C "$repo_root" status --porcelain --untracked-files=all)" ]]; then
  printf 'Refusing to publish from a dirty worktree; use a clean reviewed commit.\n' >&2
  exit 1
fi

source_sha="$(git -C "$repo_root" rev-parse --verify HEAD)"
if [[ ! "$source_sha" =~ ^[0-9a-f]{40}$ ]]; then
  printf 'Could not resolve a full commit SHA for the build context.\n' >&2
  exit 1
fi

aws_account_id="$(aws sts get-caller-identity --query Account --output text --region "$aws_region")"
repository_uri="$(aws ecr describe-repositories \
  --repository-names "$repository_name" \
  --query 'repositories[0].repositoryUri' \
  --output text \
  --region "$aws_region")"
tag_mutability="$(aws ecr describe-repositories \
  --repository-names "$repository_name" \
  --query 'repositories[0].imageTagMutability' \
  --output text \
  --region "$aws_region")"
scan_on_push="$(aws ecr describe-repositories \
  --repository-names "$repository_name" \
  --query 'repositories[0].imageScanningConfiguration.scanOnPush' \
  --output text \
  --region "$aws_region")"
encryption_type="$(aws ecr describe-repositories \
  --repository-names "$repository_name" \
  --query 'repositories[0].encryptionConfiguration.encryptionType' \
  --output text \
  --region "$aws_region")"

if [[ "$repository_uri" != "$aws_account_id.dkr.ecr."*"/$repository_name" ]]; then
  printf 'The ECR repository is not in the selected AWS account or has an unexpected URI.\n' >&2
  exit 1
fi
if [[ "$tag_mutability" != "IMMUTABLE" || "$scan_on_push" != "True" || "$encryption_type" != "KMS" ]]; then
  printf 'ECR must be immutable, KMS-encrypted, and scan images on push before publication.\n' >&2
  exit 1
fi

registry="${repository_uri%/*}"
image_tag="sha-${source_sha}"
image_ref="${repository_uri}:${image_tag}"

aws ecr get-login-password --region "$aws_region" \
  | docker login --username AWS --password-stdin "$registry" >&2

docker buildx build \
  --platform linux/amd64 \
  --push \
  --file "$repo_root/packages/access-kit/Dockerfile" \
  --tag "$image_ref" \
  "$repo_root" >&2

image_digest="$(aws ecr describe-images \
  --repository-name "$repository_name" \
  --image-ids "imageTag=$image_tag" \
  --query 'imageDetails[0].imageDigest' \
  --output text \
  --region "$aws_region")"

if [[ ! "$image_digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  printf 'ECR returned an invalid image digest for %s.\n' "$image_tag" >&2
  exit 1
fi

printf '%s\n' "$image_digest"
