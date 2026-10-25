# The walkthrough agent on Bedrock AgentCore Runtime
# ECR repository for walkthrough agent container
resource "aws_ecr_repository" "agent_walkthrough" {
  name                 = "${var.PrefixCode}/agent-walkthrough"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.datalake.arn
  }
  tags = {
    Name         = "${var.PrefixCode}-ecr-agent-walkthrough"
    resourcetype = "compute"
    codeblock    = "73-agentcore-walkthrough"
  }
}
# Image tag written by CodeBuild after each push and read here for container_uri
resource "aws_ssm_parameter" "walkthrough_image_tag" {
  name   = "/${var.PrefixCode}/walkthrough-image-tag"
  type   = "SecureString"
  key_id = aws_kms_key.datalake.arn
  value  = "initial"
  lifecycle { ignore_changes = [value] }
  tags = {
    Name         = "${var.PrefixCode}-ssm-walkthrough-image-tag"
    resourcetype = "config"
    codeblock    = "73-agentcore-walkthrough"
  }
}

module "agentcore_walkthrough" {
  source             = "./modules/agentcore_runtime"
  prefix_code        = var.PrefixCode
  region             = var.Region
  account_id         = data.aws_caller_identity.current.account_id
  name               = "walkthrough"
  description        = "Government data platform walkthrough agent: guided demo with persona-based scenarios"
  ecr_repository_arn = aws_ecr_repository.agent_walkthrough.arn
  image_uri          = "${aws_ecr_repository.agent_walkthrough.repository_url}:${aws_ssm_parameter.walkthrough_image_tag.value}"
  subnet_ids         = aws_subnet.private[*].id
  security_group_ids = [aws_security_group.agentcore_aws_only.id]
  model_ids          = [var.BedrockModelSmart]
  kms_key_arn        = aws_kms_key.datalake.arn
  codeblock          = "73-agentcore-walkthrough"

  environment = {
    REDSHIFT_WORKGROUP         = aws_redshiftserverless_workgroup.main.workgroup_name
    REDSHIFT_DATABASE          = aws_redshiftserverless_namespace.main.db_name
    BEDROCK_MODEL_ID           = var.BedrockModelSmart
    DATASET_TRACKING_TABLE     = aws_dynamodb_table.dataset_tracking.name
    DATA_SOURCE_REGISTRY_TABLE = aws_dynamodb_table.data_source_registry.name
    PLATFORM_FACTS_BUCKET      = module.datalake.bucket_id
    PLATFORM_FACTS_KEY         = aws_s3_object.platform_facts.key
    # A content hash (the SSE-KMS ETag isn't predictable) that rolls the runtime version when the facts change
    PLATFORM_FACTS_HASH = md5(jsonencode(local.platform_facts))
  }

  additional_iam_statements = [
    {
      Sid    = "RedshiftDataAPI"
      Effect = "Allow"
      Action = [
        "redshift-data:ExecuteStatement",
        "redshift-data:DescribeStatement",
        "redshift-data:GetStatementResult",
        "redshift-data:CancelStatement",
        "redshift-serverless:GetCredentials"
      ]
      Resource = ["*"]
    },
    {
      Sid      = "PlatformFactsRead"
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = ["${module.datalake.bucket_arn}/${aws_s3_object.platform_facts.key}"]
    },
    {
      Sid      = "DatasetTracking"
      Effect   = "Allow"
      Action   = ["dynamodb:BatchWriteItem"]
      Resource = [aws_dynamodb_table.dataset_tracking.arn]
    },
    {
      Sid      = "DataSourceRegistry"
      Effect   = "Allow"
      Action   = ["dynamodb:Scan"]
      Resource = [aws_dynamodb_table.data_source_registry.arn]
    },
    {
      Sid    = "KMSDynamoDB"
      Effect = "Allow"
      Action = [
        "kms:Decrypt",
        "kms:GenerateDataKey",
        "kms:DescribeKey"
      ]
      Resource = [aws_kms_key.datalake.arn]
    }
  ]

  # The delivery needs the resource policy on the vended log group pattern before it's created
  depends_on = [aws_cloudwatch_log_resource_policy.vended_logs_delivery]
}
