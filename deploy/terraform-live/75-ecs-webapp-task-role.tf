# Webapp task role: what the GOV.UK frontend may call on the agents' behalf

# Webapp task role: AgentCore, DynamoDB, S3 boundaries, Redshift nearest-area lookup, map tiles, CloudWatch Logs Insights for /admin
resource "aws_iam_role" "webapp_task" {
  name = "${var.PrefixCode}-iamrole-webapp-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name         = "${var.PrefixCode}-iamrole-webapp-task"
    resourcetype = "security"
    codeblock    = "75-ecs-webapp-task-role"
  }
}

# nosemgrep: no-iam-data-exfiltration, actions scoped to specific resources (S3 prefix, DynamoDB table ARN)
resource "aws_iam_role_policy" "webapp_task" {
  #checkov:skip=CKV_AWS_355:Redshift Data API, X-Ray, and Geo Maps actions require Resource=* (https://docs.aws.amazon.com/en_us/service-authorization/latest/reference/list_amazonlocationservicemaps.html)
  #checkov:skip=CKV_AWS_290:Webapp needs write access to DynamoDB shared answers and CloudWatch logs
  name = "${var.PrefixCode}-policy-webapp-task"
  role = aws_iam_role.webapp_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "SSMParameter"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = ["arn:aws:ssm:${var.Region}:${data.aws_caller_identity.current.account_id}:parameter/${var.PrefixCode}/*"]
      },
      {
        Sid    = "KMSDecrypt"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]
        Resource = [aws_kms_key.datalake.arn]
      },
      {
        Sid      = "InvokeAgentCore"
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:InvokeAgentRuntime", "bedrock-agentcore:StopRuntimeSession"]
        Resource = ["arn:aws:bedrock-agentcore:${var.Region}:${data.aws_caller_identity.current.account_id}:runtime/*"]
      },
      {
        Sid    = "DynamoDBRead"
        Effect = "Allow"
        Action = ["dynamodb:Scan", "dynamodb:Query"]
        Resource = [
          aws_dynamodb_table.data_source_registry.arn,
          aws_dynamodb_table.dataset_tracking.arn,
        ]
      },
      {
        Sid      = "DynamoDBSharedAnswers"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:GetItem"]
        Resource = [aws_dynamodb_table.shared_answers.arn]
      },
      {
        Sid      = "DashboardLive"
        Effect   = "Allow"
        Action   = ["dynamodb:UpdateItem"]
        Resource = [aws_dynamodb_table.dashboard_live.arn]
      },
      {
        Sid    = "S3Boundaries"
        Effect = "Allow"
        # nosemgrep: no-iam-data-exfiltration, s3:GetObject scoped to specific S3 prefix
        Action   = ["s3:GetObject"]
        Resource = ["${module.datalake.bucket_arn}/bronze/ons/geography/*"]
      },
      {
        Sid    = "RedshiftNearestArea"
        Effect = "Allow"
        Action = [
          "redshift-data:ExecuteStatement",
          "redshift-data:DescribeStatement",
          "redshift-data:GetStatementResult",
        ]
        Resource = "*"
      },
      {
        Sid      = "RedshiftCredentials"
        Effect   = "Allow"
        Action   = ["redshift-serverless:GetCredentials"]
        Resource = aws_redshiftserverless_workgroup.main.arn
      },
      {
        Sid    = "XRayTracing"
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets"
        ]
        Resource = "*"
      },
      {
        Sid    = "GeoMaps"
        Effect = "Allow"
        Action = [
          "geo-maps:GetTile",
          "geo-maps:GetStyleDescriptor",
          "geo-maps:GetGlyphs",
          "geo-maps:GetSprites"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogsInsights"
        Effect = "Allow"
        Action = [
          "logs:StartQuery",
          "logs:GetQueryResults"
        ]
        Resource = [
          "${module.agentcore_agent.vended_log_group_arn}:*",
          "${module.agentcore_walkthrough.vended_log_group_arn}:*",
          "${module.agentcore_geospatial.vended_log_group_arn}:*",
          "arn:aws:logs:${var.Region}:${data.aws_caller_identity.current.account_id}:log-group:aws/spans:*"
        ]
      },
    ]
  })
}
