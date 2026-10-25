# Lambda function with its IAM role, KMS-encrypted log group and X-Ray tracing

resource "aws_iam_role" "this" {
  name = "${var.prefix_code}-iamrole-${var.name}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })

  tags = {
    Name         = "${var.prefix_code}-iamrole-${var.name}"
    resourcetype = "security"
    codeblock    = var.codeblock
  }
}

locals {
  log_group_name = "/aws/lambda/${var.prefix_code}-lambda-${var.name}"

  kms_iam_statements = var.kms_key_arn != null ? [{
    Effect = "Allow"
    Action = [
      "kms:Decrypt",
      "kms:GenerateDataKey"
    ]
    Resource = var.kms_key_arn
  }] : []

  # Lambda manages the network interfaces itself when the function is in the VPC (https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html#vpc-permissions)
  vpc_iam_statements = length(var.vpc_subnet_ids) > 0 ? [{
    Effect = "Allow"
    Action = [
      "ec2:CreateNetworkInterface",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeSubnets",
      "ec2:DeleteNetworkInterface",
      "ec2:AssignPrivateIpAddresses",
      "ec2:UnassignPrivateIpAddresses"
    ]
    Resource = "*"
  }] : []
}

resource "aws_iam_role_policy" "this" {
  #checkov:skip=CKV_AWS_355:X-Ray and the EC2 network interface actions have no resource-level permissions (https://docs.aws.amazon.com/service-authorization/latest/reference/list_awsx-ray.html)
  name = "${var.prefix_code}-policy-${var.name}"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.this.arn}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets"
        ]
        Resource = "*"
      }
    ], local.kms_iam_statements, local.vpc_iam_statements, var.additional_iam_statements)
  })
}

data "archive_file" "this" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${var.source_dir}.zip"
}

resource "aws_lambda_function" "this" {
  #checkov:skip=CKV_AWS_116:Invoked by Step Functions (with Catch) or EventBridge Scheduler (with retries), a DLQ would be redundant
  #checkov:skip=CKV_AWS_272:Code signing not used, deployment is controlled by the pipeline role
  #checkov:skip=CKV_AWS_117:The ingest functions call public data APIs and stay outside the VPC; the gateway tools pass vpc_subnet_ids
  function_name                  = "${var.prefix_code}-lambda-${var.name}"
  role                           = aws_iam_role.this.arn
  handler                        = var.handler
  runtime                        = var.runtime
  architectures                  = ["arm64"]
  timeout                        = var.timeout
  memory_size                    = var.memory_size
  filename                       = data.archive_file.this.output_path
  source_code_hash               = data.archive_file.this.output_base64sha256
  reserved_concurrent_executions = 10
  layers                         = var.layers
  kms_key_arn                    = var.kms_key_arn # nosemgrep: aws-lambda-environment-unencrypted, the key is passed by the caller

  environment {
    variables = merge({ LOG_LEVEL = "INFO" }, var.environment_variables)
  }

  dynamic "vpc_config" {
    for_each = length(var.vpc_subnet_ids) > 0 ? [1] : []
    content {
      subnet_ids         = var.vpc_subnet_ids
      security_group_ids = var.vpc_security_group_ids
    }
  }

  # Names the pre-created group, which also makes the function wait for it rather than creating its own on first invoke
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.this.name
  }

  tracing_config {
    mode = "Active"
  }

  tags = {
    Name         = "${var.prefix_code}-lambda-${var.name}"
    resourcetype = "compute"
    codeblock    = var.codeblock
  }
}

resource "aws_cloudwatch_log_group" "this" {
  name              = local.log_group_name
  retention_in_days = 365
  kms_key_id        = var.kms_key_arn

  tags = {
    Name         = "${var.prefix_code}-logs-${var.name}"
    resourcetype = "monitoring"
    codeblock    = var.codeblock
  }
}
