data "aws_caller_identity" "current" {}

# account_id, region, prefix locals defined in iam-policy.tf

# KMS key for the state bucket
resource "aws_kms_key" "tfstate" {
  #checkov:skip=CKV2_AWS_64:Key policy uses default account root, sufficient for single-account state bucket
  description             = "KMS key for Terraform state bucket encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  tags = {
    Name         = "${var.prefix_code}-kms-tfstate"
    resourcetype = "security"
    codeblock    = "main"
  }
}

resource "aws_kms_alias" "tfstate" {
  name          = "alias/${var.prefix_code}-tfstate"
  target_key_id = aws_kms_key.tfstate.key_id
}

# S3 bucket for Terraform state
# nosemgrep: aws-s3-bucket-versioning-not-enabled, versioning configured via aws_s3_bucket_versioning.tfstate
resource "aws_s3_bucket" "tfstate" {
  #checkov:skip=CKV2_AWS_61:Terraform state bucket, no lifecycle needed, state must be retained indefinitely
  #checkov:skip=CKV_AWS_18:Terraform state bucket, access audited via CloudTrail, not a data bucket
  #checkov:skip=CKV_AWS_144:Single-region deployment, cross-region replication not needed for state
  #checkov:skip=CKV2_AWS_62:Terraform state bucket, no event notifications needed
  bucket        = "${var.prefix_code}-tfstate-${local.account_id}-${var.aws_region}"
  force_destroy = true

  tags = {
    Name         = "${var.prefix_code}-tfstate"
    resourcetype = "storage"
    codeblock    = "main"
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    bucket_key_enabled       = false
    blocked_encryption_types = ["SSE-C"]

    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.tfstate.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnforceSecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.tfstate.arn,
          "${aws_s3_bucket.tfstate.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
      {
        Sid       = "EnforceTLS12"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.tfstate.arn,
          "${aws_s3_bucket.tfstate.arn}/*"
        ]
        Condition = {
          NumericLessThan = {
            "s3:TlsVersion" = "1.2"
          }
        }
      },
      {
        Sid       = "DenyDeleteStateObjects"
        Effect    = "Deny"
        Principal = "*"
        Action = [
          "s3:DeleteObject",
          "s3:DeleteObjectVersion"
        ]
        Resource = "${aws_s3_bucket.tfstate.arn}/*.tfstate"
      }
    ]
  })
}

# local-exec rather than aws_glue_catalog: an existing account-wide s3tablescatalog is reused and never deleted on destroy. AlreadyExistsException is the expected failure
locals {
  s3tables_catalog_input = jsonencode({
    FederatedCatalog = {
      Identifier     = "arn:aws:s3tables:${var.aws_region}:${local.account_id}:bucket/*"
      ConnectionName = "aws:s3tables"
    }
    CreateDatabaseDefaultPermissions = [{ Principal = { DataLakePrincipalIdentifier = "IAM_ALLOWED_PRINCIPALS" }, Permissions = ["ALL"] }]
    CreateTableDefaultPermissions    = [{ Principal = { DataLakePrincipalIdentifier = "IAM_ALLOWED_PRINCIPALS" }, Permissions = ["ALL"] }]
  })
}

resource "terraform_data" "s3tables_catalog" {
  triggers_replace = [var.aws_region]

  provisioner "local-exec" {
    command = <<-EOT
      aws glue create-catalog --name s3tablescatalog --region ${var.aws_region} \
        --catalog-input '${local.s3tables_catalog_input}' > /tmp/s3tables-catalog.log 2>&1 \
        || grep -q AlreadyExistsException /tmp/s3tables-catalog.log \
        || { cat /tmp/s3tables-catalog.log; exit 1; }
    EOT
  }
}
