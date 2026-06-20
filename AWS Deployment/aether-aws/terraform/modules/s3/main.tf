# ============================================================================
# AETHER — S3 Module
#
# Provisions three buckets with consistent security baseline:
#   - ml_artifacts: versioned artifact store for trained models (read/write IAM)
#   - cdn:          static-asset origin for CloudFront (app JS/CSS bundles)
#   - dashboard:    Kyber dashboard assets served via CloudFront
#
# All buckets: public access blocked, SSE-S3 encryption, versioning enabled.
# ML artifacts bucket: lifecycle transitions non-current versions to IA after
# 30 days and expires them after 90 days to limit storage costs while
# preserving rollback capability within the retention window.
# Cross-region replication is conditional on var.enable_replication (production
# only). The replication role and DR bucket name are managed here; the DR
# bucket itself must be pre-created in var.dr_region.
# ============================================================================

# ── ML Artifacts ─────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "ml_artifacts" {
  bucket = "${var.project}-${var.environment}-ml-artifacts"

  tags = {
    Name        = "${var.project}-${var.environment}-ml-artifacts"
    Environment = var.environment
    Purpose     = "ML artifact storage"
  }
}

resource "aws_s3_bucket_public_access_block" "ml_artifacts" {
  bucket                  = aws_s3_bucket.ml_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "ml_artifacts" {
  bucket = aws_s3_bucket.ml_artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ml_artifacts" {
  bucket = aws_s3_bucket.ml_artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "ml_artifacts" {
  bucket = aws_s3_bucket.ml_artifacts.id

  rule {
    id     = "transition-and-expire-noncurrent-versions"
    status = "Enabled"

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ── CDN Bucket ───────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "cdn" {
  bucket = "${var.project}-${var.environment}-cdn"

  tags = {
    Name        = "${var.project}-${var.environment}-cdn"
    Environment = var.environment
    Purpose     = "CDN static assets"
  }
}

resource "aws_s3_bucket_public_access_block" "cdn" {
  bucket                  = aws_s3_bucket.cdn.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "cdn" {
  bucket = aws_s3_bucket.cdn.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cdn" {
  bucket = aws_s3_bucket.cdn.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# ── Dashboard Bucket ─────────────────────────────────────────────────────────

resource "aws_s3_bucket" "dashboard" {
  bucket = "${var.project}-${var.environment}-dashboard"

  tags = {
    Name        = "${var.project}-${var.environment}-dashboard"
    Environment = var.environment
    Purpose     = "Dashboard static assets"
  }
}

resource "aws_s3_bucket_public_access_block" "dashboard" {
  bucket                  = aws_s3_bucket.dashboard.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# ── Cross-Region Replication (production only) ────────────────────────────────

resource "aws_iam_role" "replication" {
  count = var.enable_replication ? 1 : 0
  name  = "${var.project}-${var.environment}-s3-replication"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "replication" {
  count  = var.enable_replication ? 1 : 0
  name   = "ml-artifacts-replication"
  role   = aws_iam_role.replication[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetReplicationConfiguration", "s3:ListBucket"]
        Resource = [aws_s3_bucket.ml_artifacts.arn]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObjectVersionForReplication",
          "s3:GetObjectVersionAcl",
          "s3:GetObjectVersionTagging",
        ]
        Resource = ["${aws_s3_bucket.ml_artifacts.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ReplicateObject", "s3:ReplicateDelete", "s3:ReplicateTags"]
        Resource = ["arn:aws:s3:::${var.project}-${var.environment}-ml-artifacts-dr/*"]
      },
    ]
  })
}

resource "aws_s3_bucket_replication_configuration" "ml_artifacts" {
  count  = var.enable_replication ? 1 : 0
  bucket = aws_s3_bucket.ml_artifacts.id
  role   = aws_iam_role.replication[0].arn

  rule {
    id     = "ml-artifacts-dr"
    status = "Enabled"

    destination {
      bucket        = "arn:aws:s3:::${var.project}-${var.environment}-ml-artifacts-dr"
      storage_class = "STANDARD_IA"
    }
  }

  depends_on = [aws_s3_bucket_versioning.ml_artifacts]
}

# ── Least-Privilege IAM Policies ──────────────────────────────────────────────

resource "aws_iam_policy" "ml_artifacts_read" {
  name        = "${var.project}-${var.environment}-ml-artifacts-read"
  description = "Least-privilege read access to the ML artifacts bucket; attach to serving task role"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion", "s3:ListBucket"]
        Resource = [aws_s3_bucket.ml_artifacts.arn, "${aws_s3_bucket.ml_artifacts.arn}/*"]
      },
    ]
  })
}

resource "aws_iam_policy" "ml_artifacts_write" {
  name        = "${var.project}-${var.environment}-ml-artifacts-write"
  description = "Least-privilege write access to the ML artifacts bucket; attach to training task role"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:PutObjectTagging",
          "s3:DeleteObject",
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:ListBucket",
          "s3:ListBucketVersions",
        ]
        Resource = [aws_s3_bucket.ml_artifacts.arn, "${aws_s3_bucket.ml_artifacts.arn}/*"]
      },
    ]
  })
}
