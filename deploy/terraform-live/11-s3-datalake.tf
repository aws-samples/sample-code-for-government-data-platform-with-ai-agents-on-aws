# Data lake KMS key, bronze bucket, CloudTrail for S3 data events

locals {
  cloudtrail_arn    = "arn:aws:cloudtrail:${var.Region}:${data.aws_caller_identity.current.account_id}:trail/${var.PrefixCode}-cloudtrail"
  cloudtrail_bucket = "${var.PrefixCode}-cloudtrail-${data.aws_caller_identity.current.account_id}"
}

resource "aws_kms_key" "datalake" {
  #checkov:skip=CKV_AWS_109:The root statement is how KMS keys stay administrable (https://docs.aws.amazon.com/kms/latest/developerguide/key-policy-default.html)
  #checkov:skip=CKV_AWS_111:Same root statement
  #checkov:skip=CKV_AWS_356:Same root statement
  description             = "KMS key for data lake encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootPermissions"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowCloudTrail"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action = [
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = local.cloudtrail_arn
          }
          StringLike = {
            "kms:EncryptionContext:aws:cloudtrail:arn" = "arn:aws:cloudtrail:*:${data.aws_caller_identity.current.account_id}:trail/*"
          }
        }
      },
      {
        Sid       = "AllowBedrock"
        Effect    = "Allow"
        Principal = { Service = "bedrock.amazonaws.com" }
        Action = [
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      },
      {
        Sid       = "AllowEventBridgeScheduler"
        Effect    = "Allow"
        Principal = { Service = "scheduler.amazonaws.com" }
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      },
      {
        Sid       = "AllowCloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${var.Region}.amazonaws.com" }
        Action = [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:Describe*"
        ]
        Resource = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${var.Region}:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      }
    ]
  })

  tags = {
    Name         = "${var.PrefixCode}-kms-datalake"
    resourcetype = "security"
    codeblock    = "11-s3-datalake"
  }
}

resource "aws_kms_alias" "datalake" {
  name          = "alias/${var.PrefixCode}-datalake"
  target_key_id = aws_kms_key.datalake.key_id
}

# Bronze bucket with lifecycle tiering to IA and Glacier; silver and gold live in S3 Tables
module "datalake" {
  source      = "./modules/s3_bucket"
  name        = "${var.PrefixCode}-datalake-${data.aws_caller_identity.current.account_id}"
  kms_key_arn = aws_kms_key.datalake.arn
  codeblock   = "11-s3-datalake"

  lifecycle_rules = [
    {
      id     = "bronze-lifecycle"
      prefix = "bronze/"
      transitions = [
        { days = 90, storage_class = "STANDARD_IA" },
        { days = 365, storage_class = "GLACIER" }
      ]
    }
  ]
}

# Separate bucket for CloudTrail logs (7 year retention for audit compliance)
module "cloudtrail_logs" {
  source      = "./modules/s3_bucket"
  name        = local.cloudtrail_bucket
  kms_key_arn = aws_kms_key.datalake.arn
  codeblock   = "11-s3-datalake"

  lifecycle_rules = [
    {
      id = "cloudtrail-lifecycle"
      transitions = [
        { days = 90, storage_class = "STANDARD_IA" },
        { days = 365, storage_class = "GLACIER" }
      ]
      expiration_days = 2555
    }
  ]

  additional_bucket_policy_statements = [
    {
      Sid       = "AWSCloudTrailAclCheck"
      Effect    = "Allow"
      Principal = { Service = "cloudtrail.amazonaws.com" }
      Action    = "s3:GetBucketAcl"
      Resource  = "arn:aws:s3:::${local.cloudtrail_bucket}"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = local.cloudtrail_arn
        }
      }
    },
    {
      Sid       = "AWSCloudTrailWrite"
      Effect    = "Allow"
      Principal = { Service = "cloudtrail.amazonaws.com" }
      Action    = "s3:PutObject"
      Resource  = "arn:aws:s3:::${local.cloudtrail_bucket}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
      Condition = {
        StringEquals = {
          "s3:x-amz-acl"  = "bucket-owner-full-control"
          "AWS:SourceArn" = local.cloudtrail_arn
        }
      }
    }
  ]
}

# Audit trail for all S3 data access (who read/wrote what in the data lake)
resource "aws_cloudtrail" "datalake" {
  #checkov:skip=CKV_AWS_67:Trail scoped to S3 data events only, management events are the account trail's job
  #checkov:skip=CKV_AWS_252:Audit trail, not real-time alerting, no SNS topic
  #checkov:skip=CKV2_AWS_10:Trail logs stay in S3 with 7-year retention, no CloudWatch Logs delivery
  name                          = "${var.PrefixCode}-cloudtrail"
  s3_bucket_name                = module.cloudtrail_logs.bucket_id
  include_global_service_events = false
  is_multi_region_trail         = false
  enable_logging                = true
  enable_log_file_validation    = true
  kms_key_id                    = aws_kms_key.datalake.arn

  event_selector {
    read_write_type           = "All"
    include_management_events = false

    data_resource {
      type   = "AWS::S3::Object"
      values = ["${module.datalake.bucket_arn}/"]
    }
  }

  tags = {
    Name         = "${var.PrefixCode}-cloudtrail"
    resourcetype = "security"
    codeblock    = "11-s3-datalake"
  }
}
