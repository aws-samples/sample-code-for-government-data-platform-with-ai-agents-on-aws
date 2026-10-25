# One Bedrock AgentCore runtime: execution role, OTEL log group and stream, the runtime in the VPC, its vended
# APPLICATION_LOGS delivery and the SSM parameter the webapp reads the runtime ARN from

locals {
  runtime_name   = "${var.prefix_code}_${var.name}"
  otel_log_group = "/aws/bedrock-agentcore/runtimes/${local.runtime_name}-DEFAULT"

  # The configured models as an inference profile plus the foundation model it routes to (the profile id carries a
  # region-family prefix such as eu. that the model id doesn't)
  model_arns = flatten([for m in distinct(var.model_ids) : [
    "arn:aws:bedrock:${var.region}:${var.account_id}:inference-profile/${m}",
    "arn:aws:bedrock:*::foundation-model/${replace(m, "/^(global|us|eu|apac|jp|au|ca|us-gov)\\./", "")}",
  ]])

  # ADOT auto-instrumentation, what AgentCore injects itself for direct code deploy
  otel_environment = {
    AWS_DEFAULT_REGION          = var.region
    AGENT_OBSERVABILITY_ENABLED = "true"
    # Keep spans in aws/spans, which the /admin viewer reads
    UNIFIED_TRACES_DESTINATION_ENABLED = "false"
    # Keep prompts and tool inputs/results on spans, which the /admin viewer reads
    AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT               = "true"
    OTEL_PYTHON_DISTRO                                 = "aws_distro"
    OTEL_PYTHON_CONFIGURATOR                           = "aws_configurator"
    OTEL_SEMCONV_STABILITY_OPT_IN                      = "gen_ai_latest_experimental"
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT = "true"
    OTEL_EXPORTER_OTLP_PROTOCOL                        = "http/protobuf"
    OTEL_TRACES_EXPORTER                               = "otlp"
    OTEL_LOGS_EXPORTER                                 = "otlp"
    OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED   = "true"
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT                 = "https://xray.${var.region}.amazonaws.com/v1/traces"
    OTEL_EXPORTER_OTLP_LOGS_ENDPOINT                   = "https://logs.${var.region}.amazonaws.com/v1/logs"
    OTEL_RESOURCE_ATTRIBUTES                           = "service.name=${local.runtime_name}.DEFAULT,aws.service.type=gen_ai_agent,cloud.platform=aws_bedrock_agentcore,cloud.provider=aws,cloud.region=${var.region},aws.log.group.names=${local.otel_log_group},aws.log.stream.names=otel-rt-logs,deployment.environment.name=bedrock-agentcore:default"
    OTEL_EXPORTER_OTLP_LOGS_HEADERS                    = "x-aws-log-group=${local.otel_log_group},x-aws-log-stream=otel-rt-logs,x-aws-metric-namespace=bedrock-agentcore"
  }
}

resource "aws_iam_role" "this" {
  name = "${var.prefix_code}-iamrole-agentcore-${var.name}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock-agentcore.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = var.account_id }
      }
    }]
  })

  tags = {
    Name         = "${var.prefix_code}-iamrole-agentcore-${var.name}"
    resourcetype = "security"
    codeblock    = var.codeblock
  }
}

# nosemgrep: no-iam-data-exfiltration, every statement is scoped to a named resource
resource "aws_iam_role_policy" "this" {
  #checkov:skip=CKV_AWS_287:ecr:GetAuthorizationToken requires Resource=*, account-level API (https://docs.aws.amazon.com/AmazonECR/latest/APIReference/API_GetAuthorizationToken.html)
  #checkov:skip=CKV_AWS_355:X-Ray and Redshift Data API actions require Resource=* (https://docs.aws.amazon.com/redshift/latest/mgmt/data-api-iam.html)
  #checkov:skip=CKV_AWS_290:Agents write to the DynamoDB tracking table and CloudWatch logs
  name = "${var.prefix_code}-policy-agentcore-${var.name}"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid    = "ECRPull"
        Effect = "Allow"
        # nosemgrep: no-iam-creds-exposure, ecr:GetAuthorizationToken is account-level, Resource=* required
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "ECRImage"
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
        Resource = [var.ecr_repository_arn]
      },
      {
        Sid    = "Bedrock"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = local.model_arns
      },
      {
        Sid    = "OTELLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams"
        ]
        Resource = "${aws_cloudwatch_log_group.otel.arn}:*"
      },
      {
        Sid    = "OTELTraces"
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords"
        ]
        Resource = "*"
      }
    ], var.additional_iam_statements)
  })
}

# OTEL log group ADOT writes to directly, read by the GenAI Observability trajectory view
resource "aws_cloudwatch_log_group" "otel" {
  name              = local.otel_log_group
  retention_in_days = 365
  kms_key_id        = var.kms_key_arn

  tags = {
    Name         = "${var.prefix_code}-logs-agentcore-${var.name}-otel"
    resourcetype = "monitoring"
    codeblock    = var.codeblock
  }
}

# ADOT won't create the stream through the OTLP endpoint
resource "aws_cloudwatch_log_stream" "otel" {
  name           = "otel-rt-logs"
  log_group_name = aws_cloudwatch_log_group.otel.name
}

resource "aws_bedrockagentcore_agent_runtime" "this" {
  agent_runtime_name = local.runtime_name
  description        = var.description
  role_arn           = aws_iam_role.this.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = var.image_uri
    }
  }

  environment_variables = merge(local.otel_environment, var.environment)

  # Private subnets with NAT egress; AgentCore creates the network interfaces through its service-linked role
  network_configuration {
    network_mode = "VPC"
    network_mode_config {
      subnets         = var.subnet_ids
      security_groups = var.security_group_ids
    }
  }

  protocol_configuration {
    server_protocol = "HTTP"
  }

  lifecycle_configuration {
    idle_runtime_session_timeout = 900
    max_lifetime                 = 28800
  }

  tags = {
    Name         = "${var.prefix_code}-agentcore-${var.name}"
    resourcetype = "compute"
    codeblock    = var.codeblock
  }
}

# Vended APPLICATION_LOGS: the request and response payloads the /admin session viewer reads
resource "aws_cloudwatch_log_group" "vended" {
  name              = "/aws/vendedlogs/bedrock-agentcore/${aws_bedrockagentcore_agent_runtime.this.agent_runtime_id}"
  retention_in_days = 365
  kms_key_id        = var.kms_key_arn

  tags = {
    Name         = "${var.prefix_code}-logs-agentcore-${var.name}-vended"
    resourcetype = "monitoring"
    codeblock    = var.codeblock
  }
}

resource "aws_cloudwatch_log_delivery_source" "logs" {
  name         = "${var.prefix_code}-agentcore-${var.name}-logs-source"
  log_type     = "APPLICATION_LOGS"
  resource_arn = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn

  tags = {
    Name         = "${var.prefix_code}-agentcore-${var.name}-logs-source"
    resourcetype = "monitoring"
    codeblock    = var.codeblock
  }
}

resource "aws_cloudwatch_log_delivery_destination" "logs" {
  name = "${var.prefix_code}-agentcore-${var.name}-logs-destination"

  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.vended.arn
  }

  tags = {
    Name         = "${var.prefix_code}-agentcore-${var.name}-logs-destination"
    resourcetype = "monitoring"
    codeblock    = var.codeblock
  }
}

resource "aws_cloudwatch_log_delivery" "logs" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.logs.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.logs.arn

  tags = {
    Name         = "${var.prefix_code}-agentcore-${var.name}-logs-delivery"
    resourcetype = "monitoring"
    codeblock    = var.codeblock
  }
}

# Runtime ARN for the webapp
resource "aws_ssm_parameter" "runtime_arn" {
  name   = "/${var.prefix_code}/${var.name}-runtime-arn"
  type   = "SecureString"
  key_id = var.kms_key_arn
  value  = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn

  tags = {
    Name         = "${var.prefix_code}-ssm-${var.name}-runtime-arn"
    resourcetype = "config"
    codeblock    = var.codeblock
  }
}
