# Geospatial satellite analysis agent on Bedrock AgentCore Runtime
# ECR repository for geospatial agent container
resource "aws_ecr_repository" "agent_geospatial" {
  name                 = "${var.PrefixCode}/agent-geospatial"
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
    Name         = "${var.PrefixCode}-ecr-agent-geospatial"
    resourcetype = "compute"
    codeblock    = "78-agentcore-geospatial"
  }
}
# Image tag written by CodeBuild after each push and read here for container_uri
resource "aws_ssm_parameter" "geospatial_image_tag" {
  name   = "/${var.PrefixCode}/geospatial-image-tag"
  type   = "SecureString"
  key_id = aws_kms_key.datalake.arn
  value  = "initial"
  lifecycle { ignore_changes = [value] }
  tags = {
    Name         = "${var.PrefixCode}-ssm-geospatial-image-tag"
    resourcetype = "config"
    codeblock    = "78-agentcore-geospatial"
  }
}

# Sentinel-2 is public HTTPS; Landsat is the requester-pays usgs-landsat bucket in us-west-2, billed to this account
module "agentcore_geospatial" {
  source             = "./modules/agentcore_runtime"
  prefix_code        = var.PrefixCode
  region             = var.Region
  account_id         = data.aws_caller_identity.current.account_id
  name               = "geospatial"
  description        = "Government data platform geospatial agent: satellite imagery analysis over England and Wales"
  ecr_repository_arn = aws_ecr_repository.agent_geospatial.arn
  image_uri          = "${aws_ecr_repository.agent_geospatial.repository_url}:${aws_ssm_parameter.geospatial_image_tag.value}"
  subnet_ids         = aws_subnet.private[*].id
  security_group_ids = [aws_security_group.agentcore.id]
  model_ids          = [var.BedrockModelSmart, var.BedrockModelFast]
  kms_key_arn        = aws_kms_key.datalake.arn
  codeblock          = "78-agentcore-geospatial"

  environment = {
    BEDROCK_MODEL_ID          = var.BedrockModelSmart
    BEDROCK_MODEL_ID_FAST     = var.BedrockModelFast
    BEDROCK_GUARDRAIL_ID      = var.BedrockGuardrailEnabled ? aws_bedrock_guardrail.agent.guardrail_id : ""
    BEDROCK_GUARDRAIL_VERSION = var.BedrockGuardrailEnabled ? aws_bedrock_guardrail_version.agent.version : ""
  }

  additional_iam_statements = [
    {
      Sid      = "BedrockGuardrail"
      Effect   = "Allow"
      Action   = ["bedrock:ApplyGuardrail"]
      Resource = [aws_bedrock_guardrail.agent.guardrail_arn]
    },
    {
      Sid      = "GuardrailKMS"
      Effect   = "Allow"
      Action   = ["kms:Decrypt", "kms:DescribeKey"]
      Resource = [aws_kms_key.datalake.arn]
    },
    {
      Sid      = "LandsatRead"
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = ["arn:aws:s3:::usgs-landsat/*"]
    }
  ]

  # The delivery needs the resource policy on the vended log group pattern before it's created
  depends_on = [aws_cloudwatch_log_resource_policy.vended_logs_delivery]
}
