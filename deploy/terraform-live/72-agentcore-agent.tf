# The data agent on Bedrock AgentCore Runtime

# ECR repository for agent container image
resource "aws_ecr_repository" "agent" {
  name                 = "${var.PrefixCode}/agent"
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
    Name         = "${var.PrefixCode}-ecr-agent"
    resourcetype = "compute"
    codeblock    = "72-agentcore-agent"
  }
}

# Image tag written by CodeBuild after each push and read here for container_uri; a fresh account starts on "initial" until the Build stage overwrites it
resource "aws_ssm_parameter" "agent_image_tag" {
  name   = "/${var.PrefixCode}/agent-image-tag"
  type   = "SecureString"
  key_id = aws_kms_key.datalake.arn
  value  = "initial"

  lifecycle { ignore_changes = [value] }

  tags = {
    Name         = "${var.PrefixCode}-ssm-agent-image-tag"
    resourcetype = "config"
    codeblock    = "72-agentcore-agent"
  }
}

module "agentcore_agent" {
  source             = "./modules/agentcore_runtime"
  prefix_code        = var.PrefixCode
  region             = var.Region
  account_id         = data.aws_caller_identity.current.account_id
  name               = "agent"
  description        = "Government data agent: natural language queries against UK government data"
  ecr_repository_arn = aws_ecr_repository.agent.arn
  image_uri          = "${aws_ecr_repository.agent.repository_url}:${aws_ssm_parameter.agent_image_tag.value}"
  subnet_ids         = aws_subnet.private[*].id
  security_group_ids = [aws_security_group.agentcore_aws_only.id]
  model_ids          = [var.BedrockModelSmart, var.BedrockModelFast]
  kms_key_arn        = aws_kms_key.datalake.arn
  codeblock          = "72-agentcore-agent"

  environment = {
    REDSHIFT_WORKGROUP         = aws_redshiftserverless_workgroup.main.workgroup_name
    REDSHIFT_DATABASE          = aws_redshiftserverless_namespace.main.db_name
    BEDROCK_MODEL_ID           = var.BedrockModelSmart
    BEDROCK_MODEL_ID_FAST      = var.BedrockModelFast
    BEDROCK_GUARDRAIL_ID       = var.BedrockGuardrailEnabled ? aws_bedrock_guardrail.agent.guardrail_id : ""
    BEDROCK_GUARDRAIL_VERSION  = var.BedrockGuardrailEnabled ? aws_bedrock_guardrail_version.agent.version : ""
    DATASET_TRACKING_TABLE     = aws_dynamodb_table.dataset_tracking.name
    DATA_SOURCE_REGISTRY_TABLE = aws_dynamodb_table.data_source_registry.name
  }

  additional_iam_statements = [
    {
      Sid    = "BedrockGuardrail"
      Effect = "Allow"
      Action = [
        "bedrock:ApplyGuardrail"
      ]
      Resource = [aws_bedrock_guardrail.agent.guardrail_arn]
    },
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
