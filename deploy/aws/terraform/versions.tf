terraform {
  required_version = "~> 1.5"

  # Remote state is mandatory for reviewed promotion: bucket/key/lock table are
  # injected per profile via `terraform init -backend-config=...` (see
  # .github/workflows/terraform-promote.yml and infrastructure.yml).
  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
    auth0 = {
      source  = "auth0/auth0"
      version = "~> 1.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}
